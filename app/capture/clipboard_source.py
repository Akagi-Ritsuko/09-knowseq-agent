"""剪贴板监控（T-105 REQ-105 / ADR-004）。

微信/企微对话入口：用户复制文本即自动入库。Windows 下用 ctypes 读取剪贴板。
非文本忽略；超长截断（config: sources.clipboard.max_len）；内容哈希去重（REQ-102）。
"""
import ctypes
from ctypes import wintypes

from .base import CaptureSource

CF_UNICODETEXT = 13

if hasattr(ctypes, "windll"):  # Windows：一次性声明 Win32 原型
    # 不声明 argtypes/restype 时，64 位下句柄被按 32 位截断成非法指针，
    # GlobalLock 后读内存直接 Access Violation —— 必须显式声明
    _user32 = ctypes.windll.user32
    _kernel32 = ctypes.windll.kernel32
    _user32.OpenClipboard.argtypes = [wintypes.HWND]
    _user32.OpenClipboard.restype = wintypes.BOOL
    _user32.CloseClipboard.argtypes = []
    _user32.CloseClipboard.restype = wintypes.BOOL
    _user32.IsClipboardFormatAvailable.argtypes = [wintypes.UINT]
    _user32.IsClipboardFormatAvailable.restype = wintypes.BOOL
    _user32.GetClipboardData.argtypes = [wintypes.UINT]
    _user32.GetClipboardData.restype = wintypes.HANDLE
    _kernel32.GlobalLock.argtypes = [wintypes.HGLOBAL]
    _kernel32.GlobalLock.restype = ctypes.c_void_p
    _kernel32.GlobalUnlock.argtypes = [wintypes.HGLOBAL]
    _kernel32.GlobalUnlock.restype = wintypes.BOOL
else:
    _user32 = _kernel32 = None


def read_clipboard_text():
    """读取剪贴板文本（Windows）。无文本、剪贴板被占用或失败返回 None。"""
    if _user32 is None:
        return None
    if not _user32.OpenClipboard(None):  # 被其他程序占用时打不开，下轮轮询重试
        return None
    try:
        if not _user32.IsClipboardFormatAvailable(CF_UNICODETEXT):
            return None
        h = _user32.GetClipboardData(CF_UNICODETEXT)
        if not h:
            return None
        p = _kernel32.GlobalLock(h)
        if not p:
            return None
        try:
            return ctypes.wstring_at(p)  # 从合法指针按宽字符读到 NUL
        finally:
            _kernel32.GlobalUnlock(h)
    finally:
        _user32.CloseClipboard()


class ClipboardSource(CaptureSource):
    name = "clipboard"

    def start(self):
        if self.status == "running":
            return
        if not self.enabled():
            self.status = "stopped"
            return
        self._spawn(self._work)

    def _work(self, stop_event) -> None:
        self.status = "running"
        self.error = ""
        interval = max(0.5, float(self.config.get("sources.clipboard.interval", 2)))
        max_len = int(self.config.get("sources.clipboard.max_len", 50000))
        # 先读一次作基线：启动前剪贴板里的旧内容不入库（REQ-105）
        seen = (read_clipboard_text() or "").strip()
        while not stop_event.is_set():
            try:
                text = read_clipboard_text()
                if text and text.strip() and text.strip() != seen:
                    text = text.strip()
                    seen = text  # 先记基线（含被截断的完整原文），避免同一内容反复触发
                    if len(text) > max_len:
                        text = text[:max_len]
                    self.inbox.write_material(
                        "clipboard", "剪贴板片段", text,
                        meta={"captured_from": "clipboard"})
            except Exception as e:  # noqa: BLE001
                self.status = "error"
                self.error = str(e)
            finally:
                stop_event.wait(interval)
