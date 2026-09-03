"""LLM 产出文档清洗（T-203 REQ-203）。

Ported from nashsu/llm_wiki (GPL-3.0) —— src/lib/ingest-sanitize.ts。
写盘前修复 LLM 生成条目的四种常见畸形：

  1. 整个文档（或 frontmatter 块）被 ```yaml / ```md 代码栅栏包裹
  2. 开头多出一行 `frontmatter:` 前缀
  3. frontmatter 缺开头 `---` 但有结尾 `---`（模型"从 YAML 内部开始写"）
  4. frontmatter 内 `related: [[a]], [[b]]` 非法 YAML 流式列表

刻意保守：各模式只锚定文档开头或 frontmatter 顶层作用域，
正文深处的合法代码栅栏与 prose 中的 "frontmatter:" 提及不受影响。
"""
import re

_BOM_FENCE_OPEN_RE = re.compile(
    r"^(?:\ufeff)?(?:[ \t]*\r?\n)*[ \t]*```(?:yaml|md|markdown)?[ \t]*\r?\n", re.IGNORECASE)
_FENCE_CLOSE_RE = re.compile(r"\r?\n[ \t]*```[ \t]*\r?\n?\s*$")
_FM_ONLY_FENCE_RE = re.compile(
    r"^(---[ \t]*\r?\n[\s\S]*?^---[ \t]*\r?\n)[ \t]*```[ \t]*(?:\r?\n|$)", re.MULTILINE)
_FM_KEY_PREFIX_RE = re.compile(r"^[ \t]*frontmatter\s*:\s*\r?\n(?=[ \t]*---\s*\r?\n)")
_FM_OPEN_RE = re.compile(r"^[ \t]*---\s*(?:\r?\n|$)")
_FIRST_KEY_RE = re.compile(
    r"^(type|title|created|updated|tags|related|sources)\s*:", re.IGNORECASE)
_HEADING_RE = re.compile(r"^#{1,6}\s+")
_FM_BLOCK_RE = re.compile(r"^(---[ \t]*(\r?\n))([\s\S]*?)(\r?\n---[ \t]*(?:\r?\n|$))")
_WIKILINK_LIST_LINE_RE = re.compile(
    r"^(\s*[A-Za-z_][\w-]*\s*:\s*)(\[\[[^\]]+\]\](?:\s*,\s*\[\[[^\]]+\]\])+)\s*$")


def sanitize_document(content: str) -> str:
    cleaned = _strip_outer_code_fence(content)
    cleaned = _strip_frontmatter_key_prefix(cleaned)
    cleaned = _add_missing_opening_frontmatter_fence(cleaned)
    cleaned = _repair_wikilink_lists_in_frontmatter(cleaned)
    return cleaned


def _strip_outer_code_fence(content: str) -> str:
    open_m = _BOM_FENCE_OPEN_RE.match(content)
    if not open_m:
        return content
    after_open = content[open_m.end():]
    close_m = _FENCE_CLOSE_RE.search(after_open)
    if close_m:
        return after_open[:close_m.start()]
    # 栅栏恰好在完整 frontmatter 块后闭合、正文在栅栏外：只剥 frontmatter 段
    fm_only = _FM_ONLY_FENCE_RE.match(after_open)
    if not fm_only:
        return content
    return fm_only.group(1) + after_open[fm_only.end():]


def _strip_frontmatter_key_prefix(content: str) -> str:
    m = _FM_KEY_PREFIX_RE.match(content)
    return content[m.end():] if m else content


def _add_missing_opening_frontmatter_fence(content: str) -> str:
    if _FM_OPEN_RE.match(content):
        return content
    lines = re.split(r"\r?\n", content)
    first = next((i for i, ln in enumerate(lines) if ln.strip()), None)
    if first is None:
        return content
    if not _FIRST_KEY_RE.match(lines[first].strip()):
        return content
    for i in range(first + 1, min(len(lines), first + 30)):
        trimmed = lines[i].strip()
        if trimmed == "---":
            return "---\n" + "\n".join(lines[first:])
        if _HEADING_RE.match(trimmed):
            break
    return content


def _repair_wikilink_lists_in_frontmatter(content: str) -> str:
    m = _FM_BLOCK_RE.match(content)
    if not m:
        return content

    def fix_line(line: str) -> str:
        lm = _WIKILINK_LIST_LINE_RE.match(line)
        if not lm:
            return line
        items = ", ".join(f'"{s.strip()}"'
                          for s in lm.group(2).split(",") if s.strip())
        return f"{lm.group(1)}[{items}]"

    repaired = m.group(2).join(
        fix_line(ln) for ln in re.split(r"\r?\n", m.group(3)))
    return m.group(1) + repaired + m.group(4) + content[m.end():]
