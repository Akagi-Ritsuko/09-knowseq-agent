"""屏幕/音频采集（T-104 REQ-104 / ADR-003）。

基于 screenpipe 本地服务：官方 Python 包 screenpipe-py 或官方应用均可，
本项目经其本地 HTTP API（http://127.0.0.1:3030/search）增量拉取 OCR/音频文本，
写入 inbox/screen/。screenpipe 服务需处于运行状态；未运行时给出明确提示。
"""
import shutil
import subprocess
import time
from datetime import datetime, timezone

import requests

from .base import CaptureSource

BASE = "http://127.0.0.1:3030"
PULL_INTERVAL = 30  # 增量拉取间隔（秒）
PAGE_LIMIT = 100


class ScreenpipeSource(CaptureSource):
    name = "screen"

    def __init__(self, config, inbox):
        super().__init__(config, inbox)
        self._cursor: str | None = None  # ISO 时间游标（增量）

    # ---- 服务探测 ----
    def server_available(self) -> bool:
        try:
            r = requests.get(f"{BASE}/search", params={"limit": 1}, timeout=3)
            return r.status_code < 500
        except Exception:  # noqa: BLE001
            return False

    def _try_start_server(self) -> str:
        """尝试用 screenpipe CLI 拉起服务；找不到则返回提示。"""
        exe = shutil.which("screenpipe")
        if not exe:
            return "未找到 screenpipe 可执行文件。请先启动 screenpipe 本地服务（官方应用或 screenpipe-py），再开启屏幕采集。"
        try:
            subprocess.Popen([exe], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            return ""
        except Exception as e:  # noqa: BLE001
            return f"启动 screenpipe 失败: {e}"

    # ---- 增量拉取 ----
    def _pull(self, content_type: str) -> str | None:
        params = {"content_type": content_type, "limit": PAGE_LIMIT,
                  "max_content_length": 8000}
        if self._cursor:
            params["start_time"] = self._cursor
        r = requests.get(f"{BASE}/search", params=params, timeout=15)
        r.raise_for_status()
        data = r.json()
        newest = self._cursor
        for item in data.get("data", []):
            content = item.get("content") or {}
            text = (content.get("text") or "").strip()
            if not text:
                continue
            meta = item.get("metadata") or {}
            ts = meta.get("timestamp") or content.get("timestamp")
            if ts and (newest is None or ts > newest):
                newest = ts
            self.inbox.write_material(
                "screen",
                f"屏幕-{content.get('type', content_type)}",
                text,
                meta={"sp_type": content.get("type"),
                      "app": meta.get("app_name"),
                      "window": meta.get("window_name"),
                      "sp_time": ts},
                dedup=True)
        return newest

    def _work(self):
        self.status = "running"
        self.error = ""
        if not self.server_available():
            msg = self._try_start_server()
            if msg:
                self.status = "error"
                self.error = msg
                return
            time.sleep(5)
        while not self._stop:
            try:
                if not self.server_available():
                    time.sleep(PULL_INTERVAL)
                    continue
                for ct in ("ocr", "audio"):
                    self._cursor = self._pull(ct) or self._cursor
                self.status = "running"
            except Exception as e:  # noqa: BLE001
                self.status = "error"
                self.error = str(e)
            finally:
                time.sleep(PULL_INTERVAL)

    def start(self):
        if self.status == "running":
            return
        if not self.enabled():
            self.status = "stopped"
            return
        self._spawn(self._work)
