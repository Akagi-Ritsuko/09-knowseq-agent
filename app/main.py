"""KnowSeq Agent 入口（T-101/T-110/T-111）。

启动：本地 FastAPI 控制台（后台线程）+ 采集管理器 + 托盘。
运行：.venv\\Scripts\\python -m app.main  或  .venv\\Scripts\\python run.py
"""
import threading

import uvicorn

from .capture.inbox import Inbox
from .capture.manager import CaptureManager
from .config import Config
from .tray import build_tray
from .web.server import create_app


def main():
    config = Config()
    inbox = Inbox(config.inbox_dir)
    manager = CaptureManager(config, inbox)
    app = create_app(config, inbox, manager)
    port = int(config.get("web.port", 8765))
    url = f"http://127.0.0.1:{port}"

    threading.Thread(
        target=uvicorn.run,
        kwargs={"app": app, "host": "127.0.0.1", "port": port, "log_level": "warning"},
        daemon=True,
    ).start()
    print(f"[knowseq-agent] 控制台: {url}")

    if config.get("web.auto_start", True):
        manager.start_all()

    tray = build_tray(manager, url)
    tray.run()


if __name__ == "__main__":
    main()
