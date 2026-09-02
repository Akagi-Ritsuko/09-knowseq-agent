"""系统托盘雏形（T-111 REQ-111 / ADR-011）。

pystray 托盘：左键单击切换采集（default=True 菜单项）；右键菜单含
开始/结束采集、打开控制台、退出。
"""
import webbrowser

import pystray
from PIL import Image, ImageDraw


def _make_icon() -> Image.Image:
    img = Image.new("RGB", (64, 64), (30, 144, 255))
    d = ImageDraw.Draw(img)
    d.ellipse([16, 16, 48, 48], fill="white")
    return img


def _toggle(manager):
    if manager.get_status()["running"]:
        manager.stop_all()
    else:
        manager.start_all()


def build_tray(manager, url: str) -> pystray.Icon:
    def on_toggle(_icon, _item):
        _toggle(manager)

    def on_open(_icon, _item):
        webbrowser.open(url)

    def on_exit(_icon, _item):
        manager.stop_all()
        _icon.stop()

    menu = pystray.Menu(
        pystray.MenuItem("切换采集（开始/结束）", on_toggle, default=True),
        pystray.MenuItem("打开控制台", on_open),
        pystray.Menu.SEPARATOR,
        pystray.MenuItem("退出", on_exit),
    )
    return pystray.Icon("knowseq-agent", _make_icon(), "KnowSeq Agent", menu)
