"""文件监听（T-107 REQ-107 / ADR-006）。

watchdog 监听配置目录 + drop 热文件夹，新增/修改的 md/txt 自动入库。
用状态文件（inbox/.file_state.json）记录已处理路径，重启不重复入库。
docx/pdf 解析 M1 先不支持（"解析按需"，见 REQ-107）。
"""
import json
from pathlib import Path

from watchdog.events import FileSystemEventHandler
from watchdog.observers import Observer

from .base import CaptureSource

SUPPORTED_EXT = {".md", ".markdown", ".txt"}


def _decode_text(data: bytes) -> str:
    for enc in ("utf-8", "gbk", "latin-1"):
        try:
            return data.decode(enc)
        except UnicodeDecodeError:
            continue
    return data.decode("utf-8", errors="replace")


class FileSource(CaptureSource):
    name = "file"

    def __init__(self, config, inbox):
        super().__init__(config, inbox)
        self._observer = None
        self._state_path = inbox.root / ".file_state.json"
        self._processed: set = self._load_state()

    def _load_state(self) -> set:
        try:
            with open(self._state_path, encoding="utf-8") as f:
                return set(json.load(f))
        except Exception:
            return set()

    def _save_state(self) -> None:
        try:
            with open(self._state_path, "w", encoding="utf-8") as f:
                json.dump(sorted(self._processed), f, ensure_ascii=False, indent=2)
        except Exception:
            pass

    def watched_dirs(self) -> list:
        dirs = [str(d) for d in (self.config.get("sources.file.dirs") or [])]
        dirs.append(str(self.config.drop_dir))
        return list(dict.fromkeys(dirs))

    def _ingest(self, path: str) -> None:
        p = Path(path)
        if p.suffix.lower() not in SUPPORTED_EXT:
            return
        key = str(p.resolve())
        if key in self._processed:
            return
        try:
            content = _decode_text(p.read_bytes()).strip()
        except Exception:
            return
        if not content:
            return
        path_written = self.inbox.write_material(
            "file", p.name, content, meta={"file": str(p)}, dedup=False)
        if path_written:
            self._processed.add(key)
            self._save_state()

    def start(self):
        if self.status == "running":
            return
        if not self.enabled():
            self.status = "stopped"
            return
        try:
            from watchdog.observers import Observer  # noqa: F811
            handler = _Handler(self)
            self._observer = Observer()
            for d in self.watched_dirs():
                Path(d).mkdir(parents=True, exist_ok=True)
                self._observer.schedule(handler, d, recursive=False)
            self._observer.start()
            self.status = "running"
            self.error = ""
        except Exception as e:  # noqa: BLE001
            self.status = "error"
            self.error = str(e)

    def stop(self):
        if self._observer:
            self._observer.stop()
            self._observer = None
        self.status = "stopped"


class _Handler(FileSystemEventHandler):
    def __init__(self, source: FileSource):
        self._source = source

    def on_created(self, event):
        if not event.is_directory:
            self._source._ingest(event.src_path)

    def on_modified(self, event):
        if not event.is_directory:
            self._source._ingest(event.src_path)
