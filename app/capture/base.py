"""采集源基类（T-103 REQ-103）。

各采集源继承 CaptureSource，实现 start/stop；背景型源用 _spawn 启动工作循环。
状态机：stopped / running / error。
"""
import threading
from typing import Callable


class CaptureSource:
    name = "base"

    def __init__(self, config, inbox):
        self.config = config
        self.inbox = inbox
        self.status = "stopped"  # stopped / running / error
        self.error = ""
        self._stop = False

    def enabled(self) -> bool:
        return bool(self.config.get(f"sources.{self.name}.enabled", False))

    def info(self) -> dict:
        return {
            "name": self.name,
            "status": self.status,
            "error": self.error,
            "enabled": self.enabled(),
        }

    def start(self) -> None:
        """启动采集。由子类实现。"""

    def stop(self) -> None:
        """停止采集。由子类实现。"""
        self._stop = True
        self.status = "stopped"

    def _spawn(self, target: Callable[[], None]) -> None:
        self._stop = False
        t = threading.Thread(target=target, name=f"capture-{self.name}", daemon=True)
        t.start()
