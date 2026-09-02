"""inbox 素材模型与写入服务（T-102 REQ-102 / ADR-013）。

素材 = inbox/<source>/ 下的单个 .md 文件（YAML frontmatter + 正文），只追加不修改。
统一入口 write_material()，所有采集源都必须通过它写入。
"""
import hashlib
import json
from datetime import datetime
from pathlib import Path
from typing import Optional

SOURCES = {"screen", "clipboard", "feishu", "file", "web", "manual"}


def _safe_id(content: str) -> str:
    return hashlib.sha1(content.encode("utf-8")).hexdigest()[:12]


class Inbox:
    def __init__(self, root: Path):
        self.root = Path(root)
        self.dedup_path = self.root / ".dedup.json"
        self._dedup: dict = self._load_dedup()  # content_hash -> 素材相对路径
        for s in SOURCES:
            (self.root / s).mkdir(parents=True, exist_ok=True)

    def _load_dedup(self) -> dict:
        try:
            with open(self.dedup_path, encoding="utf-8") as f:
                return json.load(f) or {}
        except Exception:
            return {}

    def _save_dedup(self) -> None:
        try:
            with open(self.dedup_path, "w", encoding="utf-8") as f:
                json.dump(self._dedup, f, ensure_ascii=False, indent=2)
        except Exception:
            pass

    def _content_hash(self, content: str) -> str:
        return hashlib.sha256(content.strip().encode("utf-8")).hexdigest()

    def write_material(self, source: str, title: str, content: str,
                       meta: Optional[dict] = None, dedup: bool = True) -> Optional[Path]:
        """写入一条素材。返回文件路径；内容为空或重复（dedup=True）返回 None。"""
        source = (source or "").strip().lower()
        if source not in SOURCES:
            raise ValueError(f"未知素材来源: {source!r}")
        content = (content or "").strip()
        if not content:
            return None
        content_hash = self._content_hash(content)
        if dedup and content_hash in self._dedup:
            return None

        now = datetime.now()
        filename = f"{source}_{now.strftime('%Y%m%d_%H%M%S')}_{_safe_id(content)}.md"
        path = self.root / source / filename
        meta = meta or {}
        lines = [
            "---",
            f"id: {_safe_id(content)}",
            f"source: {source}",
            f"captured_at: {now.strftime('%Y-%m-%dT%H:%M:%S')}",
        ]
        if meta:
            lines.append("meta:")
            for k, v in meta.items():
                lines.append(f"  {k}: {v}")
        lines += ["compiled: false", "---", "", f"# {title or source}", "", content]
        path.write_text("\n".join(lines), encoding="utf-8")

        if dedup:
            self._dedup[content_hash] = str(path)
            self._save_dedup()
        return path

    def list_materials(self, source: Optional[str] = None) -> list:
        """列出素材摘要（按时间倒序）。"""
        out = []
        names = {source} if source else SOURCES
        for s in sorted(names):
            d = self.root / s
            if not d.exists():
                continue
            for p in sorted(d.glob("*.md"), reverse=True):
                out.append({
                    "path": str(p.relative_to(self.root)),
                    "source": s,
                    "name": p.name,
                    "size": p.stat().st_size,
                })
        return out
