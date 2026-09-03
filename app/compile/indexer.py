"""确定性索引与日志维护（T-208 REQ-208）。

Ported from nashsu/llm_wiki (GPL-3.0) —— 编译产物的确定性 index.md 重建与
log.md 追加（原实现散落在 autoIngestImpl 内，此处独立成模块）。

update_index 全量扫描五类分区目录重建索引（验收要求 index.md 覆盖全部
条目）；entries 参数用于合并本次编译新增的 (相对路径, 标题)，防止标题
解析失败时条目缺失。文本无变化时不写盘，返回 False 供调用方判断是否
计入缓存 files_written。
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Iterable

from .materials import split_frontmatter
from .schema import CATEGORIES

_INDEX_TITLE_HEAD = 8192  # 标题提取只读文件头部


def _entry_title(path: Path, slug: str) -> str:
    """条目标题：frontmatter title → 正文首个一级标题 → slug 兜底。"""
    try:
        head = path.read_text(encoding="utf-8")[:_INDEX_TITLE_HEAD]
    except OSError:
        return slug
    meta, body = split_frontmatter(head)
    title = meta.get("title") if isinstance(meta, dict) else None
    if title:
        return str(title).strip() or slug
    match = re.search(r"^#\s+(.+?)\s*$", body, re.MULTILINE)
    return match.group(1).strip() if match else slug


def _scan_entries(knowledge_dir: Path) -> dict[str, list[tuple[str, str]]]:
    """扫描五类目录，返回 {category: [(slug, title), ...]}，slug 排序去重。"""
    found: dict[str, list[tuple[str, str]]] = {}
    seen: set[tuple[str, str]] = set()
    for cat in CATEGORIES:
        items: list[tuple[str, str]] = []
        cat_dir = knowledge_dir / cat
        if cat_dir.is_dir():
            for md in sorted(cat_dir.glob("*.md")):
                slug = md.stem
                key = (cat, slug)
                if key in seen:
                    continue
                seen.add(key)
                items.append((slug, _entry_title(md, slug)))
        found[cat] = sorted(items)
    return found


def build_index_text(knowledge_dir: Path, entries: Iterable[tuple[str, str]] = ()) -> str:
    """生成 index.md 全文：`# 知识库索引` + 每类 `## {cat}` 分区列表。"""
    scanned = _scan_entries(knowledge_dir)
    for rel, title in entries:
        parts = rel.replace("\\", "/").split("/")
        if len(parts) == 2 and parts[0] in scanned:
            slug = Path(parts[1]).stem
            known = {slug for slug, _ in scanned[parts[0]]}
            if slug not in known:
                scanned[parts[0]].append((slug, title))
                scanned[parts[0]].sort()
    lines = ["# 知识库索引", ""]
    for cat in CATEGORIES:
        lines.append(f"## {cat}")
        lines.append("")
        for slug, title in scanned[cat]:
            lines.append(f"- [[{slug}]] {title}")
        lines.append("")
    return "\n".join(lines).rstrip("\n") + "\n"


def update_index(knowledge_dir: Path, entries: Iterable[tuple[str, str]] = ()) -> bool:
    """重建 knowledge/index.md。返回是否有变更（无变化不写盘）。"""
    new_text = build_index_text(knowledge_dir, entries)
    index_path = knowledge_dir / "index.md"
    try:
        old_text = index_path.read_text(encoding="utf-8")
    except OSError:
        old_text = None
    if old_text == new_text:
        return False
    index_path.write_text(new_text, encoding="utf-8")
    return True


def append_log(knowledge_dir: Path, line: str) -> bool:
    """向 knowledge/log.md 追加一行 `- {line}`（幂等：重复行跳过）。

    返回是否实际写入。用于模型漏产 log 块时的确定性兜底条目与
    fallback 摘要（REQ-207：fallback 记 log.md 不落条目页）。
    """
    entry = f"- {line.strip()}"
    log_path = knowledge_dir / "log.md"
    try:
        text = log_path.read_text(encoding="utf-8") if log_path.exists() else ""
    except OSError:
        text = ""
    if entry in text.splitlines():
        return False
    if text and not text.endswith("\n"):
        text += "\n"
    if not text:
        text = "# 编译日志\n"
    log_path.write_text(text + entry + "\n", encoding="utf-8")
    return True
