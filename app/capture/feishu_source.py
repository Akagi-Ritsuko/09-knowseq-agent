"""飞书采集（T-106 REQ-106 / ADR-005）。

开放平台自建应用 + 机器人事件（WebSocket 长连接，无需公网回调）+ 云文档导入。
凭据放 .env：FEISHU_APP_ID / FEISHU_APP_SECRET / FEISHU_VERIFICATION_TOKEN。
无凭据或未安装 lark-oapi 时降级为 stopped/error，不影响其他源。
真实端到端联调需凭据就绪后验证（见 REQ-106 验收）。
"""
import json

from .base import CaptureSource


class FeishuSource(CaptureSource):
    name = "feishu"

    def __init__(self, config, inbox):
        super().__init__(config, inbox)
        self._client = None

    def _creds(self):
        return (self.config.secret("FEISHU_APP_ID"),
                self.config.secret("FEISHU_APP_SECRET"))

    def start(self):
        if self.status == "running":
            return
        if not self.enabled():
            self.status = "stopped"
            return
        app_id, app_secret = self._creds()
        if not app_id or not app_secret:
            self.status = "stopped"
            self.error = "缺少飞书凭据（FEISHU_APP_ID / FEISHU_APP_SECRET），请在设置页配置"
            return
        try:
            import lark_oapi  # noqa: F401
        except ImportError:
            self.status = "error"
            self.error = "未安装 lark-oapi"
            return
        self._spawn(self._work)

    # ---- 消息事件处理 ----
    def _on_message(self, data):
        try:
            msg = data.message
            chat_id = getattr(msg, "chat_id", "") or ""
            message_id = getattr(msg, "message_id", "") or ""
            raw = getattr(msg, "content", "") or ""
            try:
                text = (json.loads(raw) or {}).get("text", "")
            except Exception:  # noqa: BLE001
                text = raw
            sender = ""
            if getattr(data, "sender", None) and data.sender.sender_id:
                sender = data.sender.sender_id.open_id or ""
            self.inbox.write_material(
                "feishu", f"飞书消息 {chat_id[:8]}", text,
                meta={"chat_id": chat_id, "message_id": message_id, "sender": sender},
                dedup=False)
        except Exception as e:  # noqa: BLE001
            self.error = str(e)

    def _work(self):
        from lark_oapi.ws import Client as WsClient
        from lark_oapi.ws.handler import ClientEventHandler

        app_id, app_secret = self._creds()

        class _Handler(ClientEventHandler):
            def __init__(self, handler):
                super().__init__()
                self._handler = handler

            def on_p2_im_message_receive_v1(self, data):
                self._handler(data)

        try:
            self._client = WsClient(
                _Handler(self._on_message),
                config={"app_id": app_id, "app_secret": app_secret})
            self.status = "running"
            self.error = ""
            self._client.start()  # 长连接，阻塞运行
        except Exception as e:  # noqa: BLE001
            self.status = "error"
            self.error = str(e)

    def stop(self):
        if self._client:
            try:
                self._client.stop()
            except Exception:  # noqa: BLE001
                pass
            self._client = None
        self.status = "stopped"

    # ---- 云文档导入（REQ-106） ----
    def import_doc(self, doc_token: str) -> tuple:
        """通过 docx raw_content 接口把文档正文导入 inbox/feishu。返回 (路径, 错误)。"""
        app_id, app_secret = self._creds()
        if not app_id or not app_secret:
            return None, "缺少飞书凭据"
        try:
            from lark_oapi import Client
            from lark_oapi.api.docx.v1 import RawContentDocumentRequest
        except ImportError:
            return None, "未安装 lark-oapi"
        try:
            client = Client.builder().app_id(app_id).app_secret(app_secret).build()
            req = RawContentDocumentRequest.builder().document_id(doc_token).build()
            resp = client.docx.v1.document.raw_content(req)
            if not resp.success():
                return None, f"飞书接口错误: {resp.code} {resp.msg}"
            content = resp.data.content or ""
            if not content.strip():
                return None, "文档为空"
            path = self.inbox.write_material(
                "feishu", f"飞书文档 {doc_token[:8]}", content,
                meta={"doc_token": doc_token}, dedup=False)
            return (str(path.relative_to(self.inbox.root)) if path else None), None
        except Exception as e:  # noqa: BLE001
            return None, str(e)
