"""inbox 素材 frontmatter 解析与 compiled 标记（T-201 REQ-201 / REQ-205）。

素材文件由 app/capture/inbox.py 统一写入（YAML frontmatter + 正文，
frontmatter 固定含 compiled: false）。编译层只通过本模块读取与回写。
"""
from datetime import datetime
from pathlib import Path

import yaml


def split_frontmatter(text: str) -> tuple[dict, str]:
    """解析 YAML frontmatter，返回 (meta, body)。无/损坏时返回 ({}, 原文)。"""
    if not text.startswith("---"):
        return {}, text
    lines = text.splitlines()
    for i in range(1, len(lines)):
        if lines[i].strip() == "---":
            try:
                meta = yaml.safe_load("\n".join(lines[1:i]))
            except yaml.YAMLError:
                return {}, text
            return (meta if isinstance(meta, dict) else {}), "\n".join(lines[i + 1:])
    return {}, text


def is_compiled(path: Path) -> bool:
    """素材是否已编译（frontmatter compiled: true）。"""
    try:
        meta, _ = split_frontmatter(path.read_text(encoding="utf-8"))
    except OSError:
        return False
    return bool(meta.get("compiled"))


def mark_compiled(path: Path) -> None:
    """编译成功后回写 compiled: true + compiled_at（幂等主标记，REQ-205）。"""
    meta, body = split_frontmatter(path.read_text(encoding="utf-8"))
    meta["compiled"] = True
    meta["compiled_at"] = datetime.now().strftime("%Y-%m-%dT%H:%M:%S")
    dumped = yaml.safe_dump(
        meta, allow_unicode=True, default_flow_style=False, sort_keys=False, width=10**9)
    path.write_text("---\n" + dumped + "---\n" + body, encoding="utf-8")
