"""采集管理器（T-103 REQ-103）。

统一启停各采集源、聚合状态。托盘与控制台共用同一实例。
"""
from .base import CaptureSource
from .clipboard_source import ClipboardSource
from .feishu_source import FeishuSource
from .file_source import FileSource
from .screenpipe_source import ScreenpipeSource
from .web_source import WebSource


class CaptureManager:
    def __init__(self, config, inbox):
        self.sources: list[CaptureSource] = [
            ScreenpipeSource(config, inbox),
            ClipboardSource(config, inbox),
            FeishuSource(config, inbox),
            FileSource(config, inbox),
            WebSource(config, inbox),
        ]
        self._by_name = {s.name: s for s in self.sources}

    def get(self, name: str) -> CaptureSource | None:
        return self._by_name.get(name)

    def start_all(self):
        for s in self.sources:
            try:
                s.start()
            except Exception as e:  # noqa: BLE001
                s.status = "error"
                s.error = str(e)

    def stop_all(self):
        for s in self.sources:
            try:
                s.stop()
            except Exception:  # noqa: BLE001
                pass

    def get_status(self) -> dict:
        return {
            "running": any(s.status == "running" for s in self.sources),
            "sources": [s.info() for s in self.sources],
        }
