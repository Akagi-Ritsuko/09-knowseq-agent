"""网页抓取（T-108 REQ-108 / ADR-007）。

URL → requests 抓取 → readability-lxml 抽取正文 → 文本 → inbox（web/）。
由控制台输入 URL 触发（on-demand），无后台线程。
"""
import re

import requests
from lxml import html as lxml_html

from .base import CaptureSource

UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/120.0 Safari/537.36")


class WebSource(CaptureSource):
    name = "web"

    def start(self):
        # 网页采集为按需触发，不常驻线程；仅标记状态
        self.status = "running" if self.enabled() else "stopped"

    def stop(self):
        self.status = "stopped"

    def ingest(self, url: str) -> tuple:
        """抓取并入库。返回 (素材相对路径或 None, 错误信息或 None)。"""
        url = (url or "").strip().strip("`")  # 容忍从 markdown 复制带来的反引号
        if not url.startswith(("http://", "https://")):
            return None, "URL 需以 http:// 或 https:// 开头"
        try:
            resp = requests.get(url, timeout=20, headers={"User-Agent": UA})
            resp.raise_for_status()
            # 响应头未声明 charset 时 requests 默认按 ISO-8859-1 解码，中文页面会乱码
            if (resp.encoding or "").lower().replace("_", "-") in ("iso-8859-1", "latin-1"):
                resp.encoding = resp.apparent_encoding
        except requests.RequestException as e:  # noqa: BLE001
            return None, f"抓取失败: {e}"

        try:
            from readability import Document
            doc = Document(resp.text)
            title = (doc.short_title() or url).strip()
            body = lxml_html.fromstring(doc.content())
            text = body.text_content()
            text = re.sub(r"[ \t\r\f\v]+", " ", text)
            text = re.sub(r"\n\s*\n+", "\n", text).strip()
        except Exception as e:  # noqa: BLE001
            return None, f"正文抽取失败: {e}"

        if not text:
            if re.search(r"<script[^>]*>", resp.text, re.I):
                return None, ("页面疑似 JS 动态渲染（SPA）或需登录，纯 HTTP 抓取无正文；"
                              "建议打开页面复制正文后用「手动导入」入库")
            return None, "未抽取到正文"
        path = self.inbox.write_material(
            "web", title, text, meta={"url": url, "title": title}, dedup=True)
        if path is None:
            return None, "内容与已有素材重复"
        return str(path.relative_to(self.inbox.root)), None
