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
        self._stop_event: threading.Event | None = None

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
        """停止采集。子类实现时应调用 super().stop()。"""
        if self._stop_event is not None:
            self._stop_event.set()
        self.status = "stopped"

    def _spawn(self, target: Callable[[threading.Event], None]) -> None:
        # 每次启动发放新的 stop_event：旧线程持有旧 event（已 set）自然退出，
        # 快速 stop→start 不会让旧线程复活后与新线程双跑。
        stop_event = threading.Event()
        self._stop_event = stop_event
        t = threading.Thread(target=target, args=(stop_event,),
                             name=f"capture-{self.name}", daemon=True)
        t.start()
