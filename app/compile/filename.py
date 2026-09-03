"""knowledge/ 条目文件名生成（T-203 REQ-203）。

Ported from nashsu/llm_wiki (GPL-3.0) —— src/lib/wiki-filename.ts。
文件名 `{slug}-{YYYY-MM-DD}-{HHMMSS}.md`；slug 保留 Unicode 字母数字
（CJK 标题不再塌缩为空 slug），时间戳保证同日同名条目不冲突。
KnowSeq 适配：时间戳用本地时间（与 inbox 文件名惯例一致）。
"""
import re
import unicodedata
from datetime import datetime

_FALLBACK_SLUG = "query"


def make_entry_slug(title: str) -> str:
    normalized = unicodedata.normalize("NFKC", title).strip()
    buf: list[str] = []
    for ch in normalized:
        if ch.isspace():
            buf.append("-")
        elif ch.isalnum() or ch == "-":  # Unicode 字母/数字 + 连字符
            buf.append(ch)
    slug = re.sub(r"-+", "-", "".join(buf)).strip("-").lower()
    return slug[:50] or _FALLBACK_SLUG


def make_entry_filename(title: str, now: datetime | None = None) -> tuple[str, str]:
    """返回 (slug, filename)；注入 now 用于确定性测试。"""
    now = now or datetime.now()
    slug = make_entry_slug(title)
    return slug, f"{slug}-{now:%Y-%m-%d}-{now:%H%M%S}.md"
