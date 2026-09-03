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
        self._seen_msg_ids: set = set()  # WS 断线重连可能重推，按 message_id 去重

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
    def _on_message(self, data, stop_event) -> None:
        if stop_event.is_set():
            # SDK 的 WsClient 无 stop()，停止后到达的迟到消息直接丢弃
            return
        try:
            event = getattr(data, "event", None)
            msg = getattr(event, "message", None)
            if msg is None:
                return
            message_id = getattr(msg, "message_id", "") or ""
            if message_id:
                if message_id in self._seen_msg_ids:
                    return
                self._seen_msg_ids.add(message_id)
                if len(self._seen_msg_ids) > 2000:  # 防无限增长（个人工具，量小）
                    self._seen_msg_ids.clear()
                    self._seen_msg_ids.add(message_id)
            chat_id = getattr(msg, "chat_id", "") or ""
            raw = getattr(msg, "content", "") or ""
            try:
                text = (json.loads(raw) or {}).get("text", "")
            except Exception:  # noqa: BLE001
                text = raw
            sender = ""
            sender_id = getattr(getattr(event, "sender", None), "sender_id", None)
            if sender_id is not None:
                sender = getattr(sender_id, "open_id", "") or ""
            self.inbox.write_material(
                "feishu", f"飞书消息 {chat_id[:8]}", text,
                meta={"chat_id": chat_id, "message_id": message_id, "sender": sender},
                dedup=False)
        except Exception as e:  # noqa: BLE001
            self.error = str(e)

    def _work(self, stop_event) -> None:
        from lark_oapi import EventDispatcherHandler
        from lark_oapi.ws import Client as WsClient

        app_id, app_secret = self._creds()

        def _dispatch(data):
            self._on_message(data, stop_event)

        try:
            # 自建应用 + WS 长连接：加解密/验签由 SDK 在连接层处理，builder 传空串
            handler = (EventDispatcherHandler.builder("", "")
                       .register_p2_im_message_receive_v1(_dispatch)
                       .build())
            client = WsClient(app_id=app_id, app_secret=app_secret, event_handler=handler)
            self.status = "running"
            self.error = ""
            client.start()  # 长连接，阻塞运行；SDK 未提供 stop()
        except Exception as e:  # noqa: BLE001
            if not stop_event.is_set():
                self.status = "error"
                self.error = str(e)

    def stop(self):
        # lark-oapi 1.x 的 WsClient 未提供 stop()：长连接随守护线程存活，
        # 这里置位 stop_event 让 _on_message 丢弃后续消息。
        super().stop()

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
