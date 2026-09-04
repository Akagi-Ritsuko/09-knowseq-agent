"""右键菜单触发器（T-506 REQ-506 / ADR-011）。

pythonw 静默运行（无窗口、不闪控制台），urllib POST 本地 API 后立即退出；
后端未运行时静默失败（fire-and-forget，不打扰用户）。

用法（由注册表 command 调用，也可手动等效执行）：
  pythonw scripts/context_menu.py append <目录路径>   # 纳入 KnowSeq 采集
  pythonw scripts/context_menu.py stop_all            # 立即结束采集
"""
import json
import sys
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def _port() -> int:
    """从 config.yaml 读 web.port（不 import app 包，保持触发器极薄）。"""
    try:
        import yaml

        data = yaml.safe_load((ROOT / "config.yaml").read_text(encoding="utf-8")) or {}
        return int((data.get("web") or {}).get("port") or 8765)
    except Exception:  # noqa: BLE001 — 配置缺失/损坏回退默认端口
        return 8765


def _post(path: str, payload: dict | None = None) -> None:
    req = urllib.request.Request(
        f"http://127.0.0.1:{_port()}{path}",
        data=json.dumps(payload or {}).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    urllib.request.urlopen(req, timeout=5).read()


def main() -> None:
    argv = sys.argv[1:]
    try:
        if len(argv) >= 2 and argv[0] == "append":
            _post("/api/file_dirs/append", {"dir": argv[1]})
        elif len(argv) == 1 and argv[0] == "stop_all":
            _post("/api/stop_all")
    except Exception:  # noqa: BLE001 — 后端未运行/网络失败均静默退出
        pass


if __name__ == "__main__":
    main()
