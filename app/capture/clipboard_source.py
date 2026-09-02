"""剪贴板监控（T-105 REQ-105 / ADR-004）。

微信/企微对话入口：用户复制文本即自动入库。Windows 下用 ctypes 读取剪贴板。
非文本忽略；超长截断（config: sources.clipboard.max_len）；内容哈希去重（REQ-102）。
"""
import ctypes
import time

from .base import CaptureSource


def read_clipboard_text():
    """读取剪贴板文本（Windows）。无文本或失败返回 None。"""
    if not hasattr(ctypes, "windll"):
        return None
    user32 = ctypes.windll.user32
    kernel32 = ctypes.windll.kernel32
    if not user32.OpenClipboard(None):
        return None
    try:
        if not user32.IsClipboardFormatAvailable(13):  # CF_UNICODETEXT
            return None
        h = user32.GetClipboardData(13)
        if not h:
            return None
        p = kernel32.GlobalLock(h)
        if not p:
            return None
        try:
            return ctypes.c_wchar_p(p).value
        finally:
            kernel32.GlobalUnlock(h)
    finally:
        user32.CloseClipboard()


class ClipboardSource(CaptureSource):
    name = "clipboard"

    def start(self):
        if self.status == "running":
            return
        if not self.enabled():
            self.status = "stopped"
            return
        self._spawn(self._work)

    def _work(self):
        self.status = "running"
        self.error = ""
        interval = max(0.5, float(self.config.get("sources.clipboard.interval", 2)))
        max_len = int(self.config.get("sources.clipboard.max_len", 50000))
        while not self._stop:
            try:
                text = read_clipboard_text()
                if text and text.strip():
                    text = text.strip()
                    if len(text) > max_len:
                        text = text[:max_len]
                    self.inbox.write_material(
                        "clipboard", "剪贴板片段", text,
                        meta={"captured_from": "clipboard"})
            except Exception as e:  # noqa: BLE001
                self.status = "error"
                self.error = str(e)
            finally:
                time.sleep(interval)
