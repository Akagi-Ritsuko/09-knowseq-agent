"""Windows 集成（T-506/T-507 REQ-506/507 / ADR-011）。

全部走 HKCU（无需管理员权限）：
- 右键菜单：HKCU\\Software\\Classes\\Directory\\shell\\KnowSeq.{Capture,Stop}
  command 调 scripts/context_menu.py（pythonw 静默触发本地 HTTP API）
- 开机自启：HKCU\\Software\\Microsoft\\Windows\\CurrentVersion\\Run 键 "KnowSeq"
  = "pythonw路径" "run.py路径"（静默启动，托盘与控制台随登录运行）
"""
import sys
from pathlib import Path

import winreg

from .config import ROOT

MENU_KEY = r"Software\Classes\Directory\shell"
RUN_KEY = r"Software\Microsoft\Windows\CurrentVersion\Run"
AUTOSTART_NAME = "KnowSeq"
# (子键名, 菜单文案, 触发动作) —— 顺序即安装/卸载对象全集
MENU_ITEMS = (
    ("KnowSeq.Capture", "纳入 KnowSeq 采集", "append"),
    ("KnowSeq.Stop", "立即结束采集", "stop_all"),
)


def _pythonw() -> str:
    """当前解释器同目录的 pythonw.exe（venv 下即 .venv\\Scripts\\pythonw.exe）。"""
    return str(Path(sys.executable).with_name("pythonw.exe"))


def _trigger() -> str:
    return str(ROOT / "scripts" / "context_menu.py")


def _menu_command(action: str) -> str:
    if action == "append":
        return f'"{_pythonw()}" "{_trigger()}" append "%1"'
    return f'"{_pythonw()}" "{_trigger()}" {action}'


# ---- 右键菜单（T-506 REQ-506） ----

def context_menu_installed() -> bool:
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, rf"{MENU_KEY}\KnowSeq.Capture\command"):
            return True
    except FileNotFoundError:
        return False


def install_context_menu() -> None:
    for key_name, label, action in MENU_ITEMS:
        with winreg.CreateKey(winreg.HKEY_CURRENT_USER, rf"{MENU_KEY}\{key_name}") as k:
            winreg.SetValueEx(k, None, 0, winreg.REG_SZ, label)  # 默认值 = 菜单文案
        with winreg.CreateKey(winreg.HKEY_CURRENT_USER, rf"{MENU_KEY}\{key_name}\command") as k:
            winreg.SetValueEx(k, None, 0, winreg.REG_SZ, _menu_command(action))


def uninstall_context_menu() -> None:
    for key_name, _, _ in MENU_ITEMS:
        base = rf"{MENU_KEY}\{key_name}"
        try:
            winreg.DeleteKey(winreg.HKEY_CURRENT_USER, rf"{base}\command")
        except FileNotFoundError:
            pass  # 未安装（或只装了一半）视为已清除，继续清父键
        try:
            winreg.DeleteKey(winreg.HKEY_CURRENT_USER, base)
        except FileNotFoundError:
            pass


# ---- 开机自启（T-507 REQ-507） ----

def autostart_installed() -> bool:
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY) as k:
            winreg.QueryValueEx(k, AUTOSTART_NAME)
            return True
    except FileNotFoundError:
        return False


def set_autostart(enable: bool) -> None:
    """写/删 Run 键 "KnowSeq"（即时生效，重启后由 explorer 按 command 启动）。"""
    with winreg.CreateKey(winreg.HKEY_CURRENT_USER, RUN_KEY) as k:
        if enable:
            cmd = f'"{_pythonw()}" "{ROOT / "run.py"}"'
            winreg.SetValueEx(k, AUTOSTART_NAME, 0, winreg.REG_SZ, cmd)
        else:
            try:
                winreg.DeleteValue(k, AUTOSTART_NAME)
            except FileNotFoundError:
                pass
