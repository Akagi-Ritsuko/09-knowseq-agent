"""inbox 素材模型与写入服务（T-102 REQ-102 / ADR-013）。

素材 = inbox/<source>/ 下的单个 .md 文件（YAML frontmatter + 正文），只追加不修改。
统一入口 write_material()，所有采集源都必须通过它写入。
"""
import hashlib
import json
import threading
from datetime import datetime
from pathlib import Path
from typing import Optional

import yaml

SOURCES = {"meeting", "clipboard", "feishu", "file", "web", "manual"}


def _safe_id(content: str) -> str:
    return hashlib.sha1(content.encode("utf-8")).hexdigest()[:12]


class Inbox:
    def __init__(self, root: Path):
        self.root = Path(root)
        self.dedup_path = self.root / ".dedup.json"
        self._dedup: dict = self._load_dedup()  # content_hash -> 素材相对路径
        self._lock = threading.Lock()  # 保护去重检查 + 写文件 + 索引更新的原子性
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
        with self._lock:
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
                # meta 内容来自外部（网页标题/窗口名/文件名等），必须走 YAML 转义，
                # 否则含冒号、换行、特殊符号的值会破坏 frontmatter 结构
                dumped = yaml.safe_dump(
                    {str(k): v for k, v in meta.items()},
                    allow_unicode=True, default_flow_style=False,
                    sort_keys=False, width=10**9)
                lines.append("meta:")
                lines.extend("  " + ln for ln in dumped.rstrip("\n").splitlines())
            lines += ["compiled: false", "---", "", f"# {title or source}", "", content]
            path.write_text("\n".join(lines), encoding="utf-8")

            if dedup:
                self._dedup[content_hash] = str(path)
                self._save_dedup()
        return path

    def _read_compiled(self, path: Path) -> bool:
        """轻量读 frontmatter 顶格 compiled 行（REQ-408）。

        逐行读到第二个 --- 即止，只认顶格键，避免整文件 YAML 解析开销，
        也不会被 meta: 子键里的同名字段干扰。
        """
        try:
            with open(path, encoding="utf-8") as f:
                seen_head = False
                for line in f:
                    if line.strip() == "---":
                        if seen_head:
                            break
                        seen_head = True
                        continue
                    if line.startswith("compiled:"):
                        return line.split(":", 1)[1].strip().lower() == "true"
        except OSError:
            pass
        return False

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
                    "compiled": self._read_compiled(p),
                })
        return out

    def _resolve_rel(self, rel_path: str) -> Optional[Path]:
        """防穿越解析 inbox 相对路径：必须落在 inbox 子树内的 .md 文件。"""
        rel = Path(rel_path or "")
        if rel.is_absolute() or ".." in rel.parts:
            return None
        path = self.root / rel
        try:
            path.resolve().relative_to(self.root.resolve())
        except ValueError:
            return None
        if path.suffix != ".md" or not path.is_file():
            return None
        return path

    def read_material(self, rel_path: str) -> Optional[dict]:
        """读取素材（frontmatter 摘要 + 正文），供控制台预览（REQ-408）。"""
        path = self._resolve_rel(rel_path)
        if path is None:
            return None
        text = path.read_text(encoding="utf-8")
        lines = text.split("\n")
        fm: dict = {}
        body_start = 0
        if lines and lines[0].strip() == "---":
            for i in range(1, len(lines)):
                if lines[i].strip() == "---":
                    try:
                        fm = yaml.safe_load("\n".join(lines[1:i])) or {}
                    except yaml.YAMLError:
                        fm = {}
                    body_start = i + 1
                    break
        meta = fm.get("meta")
        return {
            "path": str(path.relative_to(self.root)),
            "source": str(fm.get("source") or path.parent.name),
            "captured_at": str(fm.get("captured_at") or ""),
            "compiled": bool(fm.get("compiled", False)),
            "meta": meta if isinstance(meta, dict) else {},
            "body": "\n".join(lines[body_start:]).strip(),
        }

    def mark_compiled(self, rel_path: str, compiled: bool) -> bool:
        """回写素材 frontmatter 的 compiled 标记（REQ-408）。返回是否成功。"""
        path = self._resolve_rel(rel_path)
        if path is None:
            return False
        with self._lock:
            lines = path.read_text(encoding="utf-8").split("\n")
            if not lines or lines[0].strip() != "---":
                return False
            head_end = None
            for i in range(1, len(lines)):
                if lines[i].strip() == "---":
                    head_end = i
                    break
            if head_end is None:
                return False
            flag = "true" if compiled else "false"
            for i in range(1, head_end):
                if lines[i].startswith("compiled:"):
                    lines[i] = f"compiled: {flag}"
                    break
            else:
                lines.insert(head_end, f"compiled: {flag}")
            path.write_text("\n".join(lines), encoding="utf-8")
        return True
