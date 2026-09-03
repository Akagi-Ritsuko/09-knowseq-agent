"""FILE/REVIEW 块解析与路径安全（T-207 REQ-207）。

Ported from nashsu/llm_wiki (GPL-3.0) —— parseFileBlocks / parseReviewBlocks /
isSafeIngestPath / countFileBlocks / shouldRunDedicatedReviewStage /
filterTruncatedFileRepairOutput。

与原实现差异：
- 路径前缀 wiki/ → knowledge/（KnowSeq 目录约定），函数名 is_safe_entry_path；
- Python re 的 \\w 是 Unicode 感知，REVIEW 正则显式用 ASCII 类对齐 JS \\w 行为
  （否则中文 type 不会被白名单拦下落 "confirm"）；
- parse_review_blocks 先做 CRLF 归一（原正则硬编码 \\n，模型输出 CRLF 时无法解析）；
- OPTIONS 简化为 label 列表（原为 {label, action} 对象且 label==action，无信息增益）；
- filter_repair_blocks 接收已解析块、返回块列表（原返回重拼文本，此处省去二次解析）。
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

# --- 正则常量（对齐 JS 源语义） ---

FILE_OPENER_RE = re.compile(r"^---\s*FILE:\s*(.+?)\s*---\s*$", re.IGNORECASE)
FILE_CLOSER_RE = re.compile(r"^---\s*END\s+FILE\s*---\s*$", re.IGNORECASE)
# 围栏行：行首至多 3 个空白 + 3 个以上相同字符（` 或 ~）
FENCE_RE = re.compile(r"^\s{0,3}(`{3,}|~{3,})")
# type 捕获组显式 ASCII 类（对齐 JS \w），白名单外的 type 落 "confirm"
REVIEW_BLOCK_RE = re.compile(
    r"---REVIEW:\s*([A-Za-z0-9_][A-Za-z0-9_-]*)\s*\|\s*(.+?)\s*---\n([\s\S]*?)---END REVIEW---"
)
# 计数用粗匹配（与原 countFileBlocks 一致；仅用于阈值判断，不要求路径合法）
FILE_BLOCK_COUNT_RE = re.compile(r"---FILE:\s*[^-]+---")
# 尾部悬挂的未闭合 REVIEW 块（触发 dedicated review stage 的信号之一）
HANGING_REVIEW_RE = re.compile(r"---REVIEW:\s*[A-Za-z0-9_-]+\s*\|[\s\S]*$", re.IGNORECASE)

REVIEW_TYPES = ("contradiction", "duplicate", "missing-page", "suggestion")
REVIEW_FALLBACK_TYPE = "confirm"

REVIEW_STAGE_MIN_SIGNAL_CHARS = 10_000
REVIEW_STAGE_MIN_FILE_BLOCKS = 4

ENTRY_DIR_PREFIX = "knowledge/"

_WINDOWS_RESERVED = frozenset(
    {"CON", "PRN", "AUX", "NUL", *{f"COM{i}" for i in range(1, 10)}, *{f"LPT{i}" for i in range(1, 10)}}
)
_WINDOWS_UNSAFE_CHARS = frozenset('<>:"|?*')


@dataclass
class ParsedFileBlock:
    """一个 ---FILE: path--- 块。path 为归一（反斜杠→斜杠）后的相对路径。"""

    path: str
    content: str


@dataclass
class ParseResult:
    """parse_file_blocks 的完整产物：成功块 + 警告 + 截断（未闭合）路径。"""

    blocks: list[ParsedFileBlock] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    truncated_paths: list[str] = field(default_factory=list)


@dataclass
class ReviewBlock:
    """一个 ---REVIEW: type | title--- 块（REQ-210 轻量闭环的输入）。"""

    type: str
    title: str
    detail: str = ""
    options: list[str] = field(default_factory=lambda: ["Approve", "Skip"])
    pages: list[str] = field(default_factory=list)
    search: list[str] = field(default_factory=list)


def _is_windows_safe_segment(seg: str) -> bool:
    if not seg:
        return False
    if any(ch in _WINDOWS_UNSAFE_CHARS for ch in seg):
        return False
    if seg != seg.rstrip(" ."):  # 结尾空格或点
        return False
    return seg.split(".", 1)[0].upper() not in _WINDOWS_RESERVED


def is_safe_entry_path(rel_path: str) -> bool:
    """rel_path 是否为安全的 knowledge/ 相对路径（对齐原 isSafeIngestPath）。

    拒绝：空串、控制字符/NUL、绝对路径、盘符、``..`` 穿越、
    Windows 不安全段（空段/非法字符/结尾空格点/保留名）；且必须 ``knowledge/`` 前缀。
    """
    if not rel_path:
        return False
    if any(ord(ch) < 0x20 for ch in rel_path):
        return False
    if re.match(r"^[A-Za-z]:", rel_path):
        return False
    normalized = rel_path.replace("\\", "/")
    if normalized.startswith("/"):  # 覆盖 / 与 \ 开头两种绝对路径
        return False
    segments = normalized.split("/")
    if ".." in segments:
        return False
    if not all(_is_windows_safe_segment(seg) for seg in segments):
        return False
    return normalized.startswith(ENTRY_DIR_PREFIX)


def parse_file_blocks(text: str) -> ParseResult:
    """解析模型产出中的 ---FILE: path--- 块（对齐原 parseFileBlocks）。

    算法：CRLF 归一 → 逐行找 opener → 围栏状态机（围栏内 closer 不生效）
    → closer 收块。三类问题产生 warning：未闭合（安全路径计入
    truncated_paths 供修复重试）、空路径、不安全路径。
    """
    result = ParseResult()
    if not text:
        return result
    lines = text.replace("\r\n", "\n").split("\n")
    i = 0
    total = len(lines)
    while i < total:
        opener = FILE_OPENER_RE.match(lines[i])
        if opener is None:
            i += 1
            continue
        raw_path = opener.group(1).strip()
        path = raw_path.replace("\\", "/")
        i += 1
        content_lines: list[str] = []
        closed = False
        fence_char = ""
        fence_len = 0
        while i < total:
            line = lines[i]
            fence = FENCE_RE.match(line)
            if fence_char:
                # 围栏内：同字符且长度 >= 开启围栏的行才闭合；closer 不生效
                if (
                    fence is not None
                    and fence.group(1)[0] == fence_char
                    and len(fence.group(1)) >= fence_len
                ):
                    fence_char = ""
                    fence_len = 0
                content_lines.append(line)
                i += 1
                continue
            if fence is not None:
                fence_char = fence.group(1)[0]
                fence_len = len(fence.group(1))
                content_lines.append(line)
                i += 1
                continue
            if FILE_CLOSER_RE.match(line):
                closed = True
                i += 1
                break
            content_lines.append(line)
            i += 1
        content = "\n".join(content_lines)
        if not closed:
            result.warnings.append(
                f"FILE 块未闭合（缺少 ---END FILE---）：{path or '(空路径)'}"
            )
            if path and is_safe_entry_path(path):
                result.truncated_paths.append(path)
            continue
        if not raw_path:
            result.warnings.append("FILE 块路径为空，已跳过")
            continue
        if not is_safe_entry_path(path):
            result.warnings.append(f"FILE 块路径不安全，已拒绝：{path}")
            continue
        result.blocks.append(ParsedFileBlock(path=path, content=content))
    return result


def parse_review_blocks(text: str) -> list[ReviewBlock]:
    """解析 ---REVIEW: type | title--- 块（对齐原 parseReviewBlocks）。

    type 白名单外落 "confirm"；body 中 OPTIONS/PAGES/SEARCH 行被剥出
    分别解析，其余行拼为 detail。原实现正则硬编码 \\n，此处先做 CRLF
    归一（缺陷修复，见模块 docstring）。
    """
    if not text:
        return []
    text = text.replace("\r\n", "\n")
    options_re = re.compile(r"^OPTIONS:\s*(.+)$", re.MULTILINE)
    pages_re = re.compile(r"^PAGES:\s*(.+)$", re.MULTILINE)
    search_re = re.compile(r"^SEARCH:\s*(.+)$", re.MULTILINE)
    out: list[ReviewBlock] = []
    for match in REVIEW_BLOCK_RE.finditer(text):
        raw_type = match.group(1).lower()
        rtype = raw_type if raw_type in REVIEW_TYPES else REVIEW_FALLBACK_TYPE
        title = match.group(2).strip()
        body = match.group(3)
        options: list[str] = ["Approve", "Skip"]
        pages: list[str] = []
        search: list[str] = []
        detail_lines: list[str] = []
        for line in body.split("\n"):
            om = options_re.match(line)
            if om is not None:
                opts = [p.strip() for p in om.group(1).split("|") if p.strip()]
                if opts:
                    options = opts
                continue
            pm = pages_re.match(line)
            if pm is not None:
                pages = [p.strip() for p in pm.group(1).split(",") if p.strip()]
                continue
            sm = search_re.match(line)
            if sm is not None:
                search = [s.strip() for s in sm.group(1).split("|") if s.strip()]
                continue
            detail_lines.append(line)
        out.append(
            ReviewBlock(
                type=rtype,
                title=title,
                detail="\n".join(detail_lines).strip(),
                options=options,
                pages=pages,
                search=search,
            )
        )
    return out


def count_file_blocks(text: str) -> int:
    """粗计 FILE 块数（对齐原 countFileBlocks，仅用于阈值判断）。"""
    return len(FILE_BLOCK_COUNT_RE.findall(text))


def should_run_dedicated_review_stage(text: str) -> bool:
    """是否值得追加一轮专职 review 提示（对齐原 shouldRunDedicatedReviewStage）。"""
    if len(text) >= REVIEW_STAGE_MIN_SIGNAL_CHARS:
        return True
    if count_file_blocks(text) >= REVIEW_STAGE_MIN_FILE_BLOCKS:
        return True
    return HANGING_REVIEW_RE.search(text) is not None


def filter_repair_blocks(
    blocks: list[ParsedFileBlock], allowed_paths: list[str] | set[str]
) -> tuple[list[ParsedFileBlock], list[str]]:
    """修复重试的输出只保留被请求的路径（对齐原 filterTruncatedFileRepairOutput）。

    路径先 ``\\``→``/`` 归一再比对；重复取首次出现。返回 (保留块, 警告)。
    """
    allowed = {p.replace("\\", "/") for p in allowed_paths}
    kept: list[ParsedFileBlock] = []
    seen: set[str] = set()
    dropped: list[str] = []
    duplicates: list[str] = []
    for block in blocks:
        if block.path not in allowed:
            dropped.append(block.path)
            continue
        if block.path in seen:
            duplicates.append(block.path)
            continue
        seen.add(block.path)
        kept.append(block)
    warnings: list[str] = []
    if dropped:
        warnings.append(f"修复输出包含未请求路径，已丢弃：{', '.join(dropped)}")
    if duplicates:
        warnings.append(f"修复输出包含重复路径，保留首次：{', '.join(duplicates)}")
    return kept, warnings
