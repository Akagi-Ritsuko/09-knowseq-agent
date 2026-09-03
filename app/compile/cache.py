"""SHA256 内容缓存（T-205 REQ-205）。

Ported from nashsu/llm_wiki (GPL-3.0) — src/lib/ingest-cache.ts。
素材内容未变且产物文件仍在磁盘时直接跳过重编；任一条件不满足即视为
缓存失效，回退完整编译。缓存持久化 `<base_dir>/.knowseq/compile-cache.json`，
以素材相对路径为 key，产物路径相对 knowledge/ 目录。
"""
import hashlib
import json
import threading
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path


def sha256_text(content: str) -> str:
    """文本 SHA256 十六进制摘要。"""
    return hashlib.sha256(content.encode("utf-8")).hexdigest()


@dataclass
class CacheEntry:
    hash: str
    timestamp: float
    files_written: list[str] = field(default_factory=list)


class IngestCache:
    def __init__(self, base_dir: Path, root: Path | None = None):
        self._path = Path(base_dir) / ".knowseq" / "compile-cache.json"
        self._root = Path(root) if root else Path(base_dir)
        self._lock = threading.Lock()  # 保护 load→save 的读改写原子性

    # ---- 持久化 ----
    def _load(self) -> dict[str, CacheEntry]:
        try:
            raw = json.loads(self._path.read_text(encoding="utf-8"))
            return {k: CacheEntry(**v) for k, v in (raw or {}).items()}
        except Exception:  # noqa: BLE001  缺失/损坏均视为空缓存
            return {}

    def _save(self, entries: dict[str, CacheEntry]) -> None:
        try:
            self._path.parent.mkdir(parents=True, exist_ok=True)
            self._path.write_text(
                json.dumps({k: asdict(v) for k, v in entries.items()}, ensure_ascii=False, indent=2),
                encoding="utf-8")
        except OSError:
            pass  # 缓存非关键，写失败不影响编译主流程

    # ---- 查询与维护 ----
    def get(self, source_path: str, content_hash: str) -> CacheEntry | None:
        """双条件命中：内容 hash 相同 且 全部产物文件仍存在；否则 None。"""
        with self._lock:
            entry = self._load().get(source_path)
            if not entry or entry.hash != content_hash:
                return None
            for f in entry.files_written:
                full = Path(f) if Path(f).is_absolute() else self._root / f
                try:
                    if not full.exists():
                        return None  # 产物已被删除 → 缓存失效，重编
                except OSError:
                    return None  # 存在性检查失败也按失效处理，宁可重编
            return entry

    def put(self, source_path: str, content_hash: str, files_written: list[str]) -> None:
        with self._lock:
            entries = self._load()
            entries[source_path] = CacheEntry(
                hash=content_hash, timestamp=time.time(),
                files_written=list(files_written))
            self._save(entries)

    def remove(self, source_path: str) -> None:
        with self._lock:
            entries = self._load()
            if entries.pop(source_path, None) is not None:
                self._save(entries)

    def sources(self) -> list[str]:
        """已有成功编译记录的素材路径（对应 listIngestedSourceIdentities）。"""
        with self._lock:
            return list(self._load())
