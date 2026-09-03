"""结构化 lint 与断链修复（T-209 REQ-209）。

Ported from nashsu/llm_wiki (GPL-3.0) —— src/lib/lint-structural-core.ts
（computeStructuralLint 纯函数核心）、src/lib/lint-fixes.ts（文本修复与
stub）、src/lib/lint.ts runStructuralLint 段（页面构建）。

与原实现差异（KnowSeq 适配）：
- 链接目标前缀 wiki/ → knowledge/（复用 blocks.ENTRY_DIR_PREFIX）；
- 断链 stub 一律路由 queries/{slug}.md：原实现保留断链目标子目录
  （如 concepts/foo-bar.md），会使 type:query 条目违反 schema 的
  type-目录一致规则（schema.py AUTHORITATIVE），故统一落 queries/；
- LLM 语义 lint（runSemanticLint）不移植（M2 裁剪）；semantic=True 仅
  启用 token 重叠的关联页建议（orphan/no-outlinks 的 suggestion 字段），
  默认 False；Levenshtein 断链建议恒开（对齐 REQ "lint.semantic=false
  时语义相似关闭" 的落地读法）；
- 新增 duplicate-name / duplicate-candidate 两类检查（REQ-209 要求覆盖
  "断链/同名/重复候选"）：同名 = 文件 stem 跨目录碰撞（warning），
  重复候选 = 归一标题相同（info，送 dedup 复核）；
- LintIssue 四字段对齐 REQ-209（kind/file/detail/suggestion），另带
  severity / broken_target 扩展字段供控制台与修复编排使用；
- detail 文案中文化。
"""

from __future__ import annotations

import math
import re
import unicodedata
from collections.abc import Callable, Iterable
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import NamedTuple

from .blocks import ENTRY_DIR_PREFIX
from .filename import make_entry_slug

# --- 相似度与建议常量（对齐 lint-structural-core.ts） ---

BROKEN_LINK_SUGGESTION_MIN_SCORE = 0.74
RELATED_PAGE_SUGGESTION_MIN_SCORE = 0.08
SAME_FOLDER_SCORE_BONUS = 0.08
SINGLE_CJK_TOKEN_WEIGHT = 0.35
SAME_BASENAME_SCORE = 0.96
CONTAINS_TARGET_SCORE = 0.82
MAX_SUGGESTION_CANDIDATES = 64
SUGGESTION_TOKEN_WINDOW = 4000

_MD_SUFFIX_RE = re.compile(r"\.md$", re.IGNORECASE)
# 提取用（alias 可选）；重写用（alias 捕获组原样保留）
_WIKILINK_RE = re.compile(r"\[\[([^\]|]+?)(?:\|[^\]]+?)?\]\]")
_WIKILINK_REWRITE_RE = re.compile(r"\[\[([^\]|]+?)(\|[^\]]+?)?\]\]")
_RELATED_HEADING_RE = re.compile(r"^##\s+Related\s*$", re.IGNORECASE | re.MULTILINE)
_FRONTMATTER_RE = re.compile(r"^---\s*\n([\s\S]*?)\n---")
_TITLE_RE = re.compile(r'^title:\s*["\']?(.+?)["\']?\s*$', re.MULTILINE)
_HEADING_RE = re.compile(r"^#\s+(.+)$", re.MULTILINE)
_TOKEN_RE = re.compile(r"[^\W_]+", re.UNICODE)
_CJK_RE = re.compile(r"[\u3400-\u9fff]")


@dataclass
class LintPage:
    """单页 lint 输入（对齐 StructuralLintPage）。"""

    short_name: str  # knowledge/ 相对路径（含 .md）
    slug: str        # 去 .md 的相对路径
    title: str
    outlinks: list[str] = field(default_factory=list)
    tokens: list[str] = field(default_factory=list)


@dataclass
class LintConfig:
    """lint 行为开关（对齐 StructuralLintConfig）。"""

    ignore_orphan: bool = False
    ignore_no_outlinks: bool = False
    ignore_pages: list[str] = field(default_factory=list)


@dataclass
class LintIssue:
    """一条 lint 发现（REQ-209：kind/file/detail/suggestion 四字段）。"""

    kind: str  # orphan / broken-link / no-outlinks / duplicate-name / duplicate-candidate
    file: str  # knowledge/ 相对路径（发起页）
    detail: str
    suggestion: str = ""     # 建议目标/来源页（可空）
    severity: str = "info"   # warning / info
    broken_target: str = ""  # broken-link 专用：断链原始目标


class StubResult(NamedTuple):
    """create_stub 的产物：knowledge/ 相对路径 + 是否新建。"""

    relative_path: str
    created: bool


# --- 纯函数核心：归一 / 相似度 / 索引 ---

def _file_name(path: str) -> str:
    return path.replace("\\", "/").rsplit("/", 1)[-1]


def normalize_target(target: str) -> str:
    """链接目标归一：``\\``→``/``、剥 knowledge/ 前缀与 .md 后缀、trim、lower。"""
    t = target.replace("\\", "/")
    if t.lower().startswith(ENTRY_DIR_PREFIX):
        t = t[len(ENTRY_DIR_PREFIX):]
    return _MD_SUFFIX_RE.sub("", t).strip().lower()


def levenshtein(a: str, b: str) -> int:
    """两行式 Levenshtein 距离（对齐原实现的双数组滚动）。"""
    if a == b:
        return 0
    if not a:
        return len(b)
    if not b:
        return len(a)
    previous = list(range(len(b) + 1))
    current = [0] * (len(b) + 1)
    for i in range(1, len(a) + 1):
        current[0] = i
        ca = a[i - 1]
        for j in range(1, len(b) + 1):
            cost = 0 if ca == b[j - 1] else 1
            current[j] = min(current[j - 1] + 1, previous[j] + 1, previous[j - 1] + cost)
        previous, current = current, previous
    return previous[-1]


def string_similarity(a: str, b: str) -> float:
    """目标串相似度：相等 1 / basename 相等 0.96 / 互相包含 0.82 /
    basename 过短（<5 字符）0 / 否则 1 − lev/max（对齐原实现）。"""
    left = normalize_target(a)
    right = normalize_target(b)
    if not left or not right:
        return 0.0
    if left == right:
        return 1.0
    left_base = _file_name(left)
    right_base = _file_name(right)
    if left_base == right_base:
        return SAME_BASENAME_SCORE
    if right in left or left in right:
        return CONTAINS_TARGET_SCORE
    if len(left_base) < 5 or len(right_base) < 5:
        return 0.0
    return 1.0 - levenshtein(left_base, right_base) / max(len(left_base), len(right_base))


def fragments(value: str) -> list[str]:
    """字符 bigram 指纹（NFKC 后），dict.fromkeys 去重保序。"""
    normalized = unicodedata.normalize("NFKC", normalize_target(value))
    chars = list(normalized)
    if len(chars) < 2:
        return [normalized] if normalized else []
    return list(dict.fromkeys(chars[i] + chars[i + 1] for i in range(len(chars) - 1)))


def _top_candidates(scores: dict[int, float], excluded: int) -> list[int]:
    """按分数降序（同分按索引升序）取前 MAX_SUGGESTION_CANDIDATES 个，排除 excluded。"""
    ranked = sorted(
        ((idx, s) for idx, s in scores.items() if idx != excluded),
        key=lambda kv: (-kv[1], kv[0]),
    )
    return [idx for idx, _ in ranked[:MAX_SUGGESTION_CANDIDATES]]


# --- 结构化 lint 纯核心 ---

def _duplicate_findings(pages: list[LintPage], ignored: set[str]) -> list[LintIssue]:
    """KnowSeq 新增：同名（stem 跨目录碰撞，warning）与重复候选（归一标题
    相同，info）。ignore_pages 命中的页不产出重复发现。"""
    def suppressed(page: LintPage) -> bool:
        return normalize_target(page.slug) in ignored or normalize_target(page.short_name) in ignored

    results: list[LintIssue] = []
    seen_stem: dict[str, LintPage] = {}
    seen_title: dict[str, LintPage] = {}
    for page in pages:
        if suppressed(page):
            continue
        stem = _MD_SUFFIX_RE.sub("", _file_name(page.short_name)).lower()
        first = seen_stem.get(stem)
        if first is not None and first.short_name != page.short_name:
            results.append(LintIssue(
                kind="duplicate-name", file=page.short_name,
                detail=f"文件名与 {first.short_name} 相同（stem 冲突），链接解析将产生歧义。",
                suggestion=first.short_name, severity="warning"))
        else:
            seen_stem[stem] = page
        title_key = normalize_target(page.title)
        first = seen_title.get(title_key)
        if title_key and first is not None:
            results.append(LintIssue(
                kind="duplicate-candidate", file=page.short_name,
                detail=f"归一标题与 {first.short_name} 相同（{page.title}），疑似重复条目，送 dedup 复核。",
                suggestion=first.short_name, severity="info"))
        else:
            seen_title[title_key] = page
    return results


def compute_structural_lint(
    pages: list[LintPage],
    on_progress: Callable[[int, int], None] | None = None,
    config: LintConfig | None = None,
    semantic: bool = False,
) -> list[LintIssue]:
    """结构化 lint 纯核心（对齐 computeStructuralLint + KnowSeq 重复检查）。

    semantic=False（默认）时跳过关联页建议（token 重叠），Levenshtein
    断链建议不受影响；ignorePages 命中的页自身不产出发现且出链不查，
    但仍作为链接目标参与解析。
    """
    config = config or LintConfig()
    token_sets = [set(p.tokens) for p in pages]
    slug_map: dict[str, int] = {}
    token_index: dict[str, list[int]] = {}
    fragment_index: dict[str, list[int]] = {}
    for i, page in enumerate(pages):
        basename = _MD_SUFFIX_RE.sub("", _file_name(page.short_name))
        slug_map[normalize_target(page.slug)] = i
        slug_map[normalize_target(basename)] = i
        for token in token_sets[i]:
            token_index.setdefault(token, []).append(i)
        for value in (page.slug, page.short_name, page.title):
            for frag in fragments(value):
                fragment_index.setdefault(frag, []).append(i)

    inbound: dict[int, int] = {}
    for page in pages:
        for link in page.outlinks:
            norm = normalize_target(link)
            target = slug_map.get(norm)
            if target is None:
                target = slug_map.get(
                    normalize_target(_MD_SUFFIX_RE.sub("", _file_name(link))))
            if target is not None:
                inbound[target] = inbound.get(target, 0) + 1

    def related_candidate(page_index: int, direction: str) -> LintPage | None:
        if not semantic:
            return None
        page = pages[page_index]
        token_set = token_sets[page_index]
        scores: dict[int, float] = {}
        # 超常见 token 不具备指向性，跳过以避免退化全对扫描
        common = max(20, math.ceil(len(pages) * 0.25))
        for token in token_set:
            matches = token_index.get(token, ())
            if len(matches) > common:
                continue
            weight = 1.0 if len(token) > 1 else SINGLE_CJK_TOKEN_WEIGHT
            for candidate in matches:
                scores[candidate] = scores.get(candidate, 0.0) + weight
        existing = {normalize_target(link) for link in page.outlinks}
        best: tuple[float, LintPage] | None = None
        for candidate_index in _top_candidates(scores, page_index):
            candidate = pages[candidate_index]
            if direction == "target":
                keys = (
                    normalize_target(candidate.slug),
                    normalize_target(candidate.short_name),
                    normalize_target(_MD_SUFFIX_RE.sub("", _file_name(candidate.short_name))),
                )
                if any(key in existing for key in keys):
                    continue
            overlap = scores.get(candidate_index, 0.0)
            bonus = (SAME_FOLDER_SCORE_BONUS
                     if page.short_name.split("/")[0] == candidate.short_name.split("/")[0]
                     else 0.0)
            score = (overlap / math.sqrt(max(1, len(token_set)) * max(1, len(token_sets[candidate_index])))
                     + bonus)
            if best is None or score > best[0]:
                best = (score, candidate)
        if best is not None and best[0] >= RELATED_PAGE_SUGGESTION_MIN_SCORE:
            return best[1]
        return None

    def broken_candidate(target: str) -> LintPage | None:
        scores: dict[int, float] = {}
        for frag in fragments(target):
            for candidate in fragment_index.get(frag, ()):
                scores[candidate] = scores.get(candidate, 0.0) + 1.0
        best: tuple[float, LintPage] | None = None
        for candidate_index in _top_candidates(scores, -1):
            candidate = pages[candidate_index]
            score = max(
                string_similarity(target, candidate.slug),
                string_similarity(target, candidate.short_name),
                string_similarity(target, candidate.title),
            )
            if best is None or score > best[0]:
                best = (score, candidate)
        if best is not None and best[0] >= BROKEN_LINK_SUGGESTION_MIN_SCORE:
            return best[1]
        return None

    results: list[LintIssue] = []
    ignored_pages = {t for t in (normalize_target(p) for p in config.ignore_pages) if t}
    total = len(pages)
    for i, page in enumerate(pages):
        # ignore 条目是 slug/路径，裸 basename 不得屏蔽嵌套同名页
        page_keys = (normalize_target(page.slug), normalize_target(page.short_name))
        ignored = any(key in ignored_pages for key in page_keys)
        if not ignored and not config.ignore_orphan and i not in inbound:
            source = related_candidate(i, "source")
            results.append(LintIssue(
                kind="orphan", file=page.short_name,
                detail="没有其他条目链接到本条目。",
                suggestion=source.short_name if source else "", severity="info"))
        if not ignored and not config.ignore_no_outlinks and not page.outlinks:
            target = related_candidate(i, "target")
            results.append(LintIssue(
                kind="no-outlinks", file=page.short_name,
                detail="本条目没有 [[wikilink]] 引用其他条目。",
                suggestion=target.short_name if target else "", severity="info"))
        links = [] if ignored else page.outlinks
        for link in links:
            basename = _MD_SUFFIX_RE.sub("", _file_name(link))
            if normalize_target(link) in slug_map or normalize_target(basename) in slug_map:
                continue
            candidate = broken_candidate(link)
            results.append(LintIssue(
                kind="broken-link", file=page.short_name,
                detail=f"断链：[[{link}]] —— 目标条目不存在。",
                suggestion=candidate.short_name if candidate else "",
                severity="warning", broken_target=link))
        if on_progress is not None and (i % 25 == 0 or i == total - 1):
            on_progress(i + 1, total)
    results.extend(_duplicate_findings(pages, ignored_pages))
    return results


# --- 页面构建（对齐原 lint.ts runStructuralLint 段） ---

def extract_wikilinks(content: str) -> list[str]:
    """提取全部 [[target]] / [[target|alias]] 的 target（trim 保留）。"""
    return [m.group(1).strip() for m in _WIKILINK_RE.finditer(content)]


def extract_title(content: str, fallback_path: str) -> str:
    """标题提取：frontmatter title → 首个 `# ` 标题 → 文件名 stem（[-_]+→空格）。"""
    m = _FRONTMATTER_RE.match(content)
    if m:
        tm = _TITLE_RE.search(m.group(1))
        if tm and tm.group(1).strip():
            return tm.group(1).strip()
    hm = _HEADING_RE.search(content)
    if hm and hm.group(1).strip():
        return hm.group(1).strip()
    return re.sub(r"[-_]+", " ", _MD_SUFFIX_RE.sub("", _file_name(fallback_path)))


def tokenize_for_suggestion(text: str) -> set[str]:
    """NFKC+lower 后按字母数字切词（len≥2）；含 CJK 的 token 逐字加入。"""
    tokens: set[str] = set()
    normalized = unicodedata.normalize("NFKC", text).lower()
    for match in _TOKEN_RE.finditer(normalized):
        token = match.group(0)
        if len(token) >= 2:
            tokens.add(token)
        if _CJK_RE.search(token):
            tokens.update(token)
    return tokens


def build_pages(knowledge_dir: Path | str) -> list[LintPage]:
    """扫描 knowledge/ 下全部 .md（按相对路径排序，排除 index.md/log.md）
    构建 LintPage 列表；不可读文件跳过（对齐原实现）。"""
    root = Path(knowledge_dir)
    files = sorted(
        (p for p in root.rglob("*.md") if p.is_file() and p.name not in ("index.md", "log.md")),
        key=lambda p: p.relative_to(root).as_posix(),
    )
    pages: list[LintPage] = []
    for path in files:
        try:
            content = path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            continue  # 跳过不可读文件
        short_name = path.relative_to(root).as_posix()
        slug = _MD_SUFFIX_RE.sub("", short_name)
        title = extract_title(content, short_name)
        slug_name = _file_name(slug)
        sample = f"{title}\n{slug_name}\n{content[:SUGGESTION_TOKEN_WINDOW]}"
        pages.append(LintPage(
            short_name=short_name, slug=slug, title=title,
            outlinks=extract_wikilinks(content),
            tokens=sorted(tokenize_for_suggestion(sample))))
    return pages


def lint_knowledge(
    knowledge_dir: Path | str,
    *,
    config: LintConfig | None = None,
    semantic: bool = False,
    on_progress: Callable[[int, int], None] | None = None,
) -> list[LintIssue]:
    """对 knowledge/ 全库做结构化 lint（REQ-209 入口）。

    semantic=True 时启用 token 重叠的关联页建议（LLM 语义 lint 不在移植
    范围）；Levenshtein 断链建议恒开。
    """
    pages = build_pages(knowledge_dir)
    return compute_structural_lint(
        pages, on_progress=on_progress, config=config, semantic=semantic)


# --- 文本修复与 stub（对齐 lint-fixes.ts） ---

def lint_link_target(target: str) -> str:
    """链接目标清洗：``\\``→``/``、剥 knowledge/ 前缀与 .md 后缀、trim（保留大小写）。"""
    t = target.replace("\\", "/")
    if t.lower().startswith(ENTRY_DIR_PREFIX):
        t = t[len(ENTRY_DIR_PREFIX):]
    return _MD_SUFFIX_RE.sub("", t).strip()


def _normalized_link_target(target: str) -> str:
    return lint_link_target(target).lower()


def _has_wikilink_to_target(content: str, target: str) -> bool:
    normalized = _normalized_link_target(target)
    return any(
        _normalized_link_target(m.group(1)) == normalized
        for m in _WIKILINK_RE.finditer(content)
    )


def append_wikilink(content: str, link: str) -> str:
    """向内容追加 - [[link]]：已有同目标链接则原样返回；已有 ## Related
    节则插入节首（不重复标题），否则尾部追加新节。"""
    link_target = lint_link_target(link)
    if _has_wikilink_to_target(content, link_target):
        return content
    link_line = f"- [[{link_target}]]"
    heading = _RELATED_HEADING_RE.search(content)
    if heading:
        insert_at = heading.end()
        return f"{content[:insert_at]}\n{link_line}{content[insert_at:]}"
    return f"{content.rstrip()}\n\n## Related\n{link_line}\n"


def rewrite_wikilink_target(content: str, old: str, new: str) -> str:
    """将内容中指向 old 的 wikilink 重写为 new（alias 原样保留）；
    不匹配时内容逐字节不变。"""
    broken = _normalized_link_target(old)
    replacement = lint_link_target(new)

    def _sub(match: re.Match[str]) -> str:
        raw_target = match.group(1)
        raw_alias = match.group(2) or ""
        if _normalized_link_target(raw_target) != broken:
            return match.group(0)
        return f"[[{replacement}{raw_alias}]]"

    return _WIKILINK_REWRITE_RE.sub(_sub, content)


def stub_relative_path(slug: str) -> str:
    """断链目标 → stub 相对路径。KnowSeq 适配：一律路由 queries/{slug}.md
    （原实现保留断链目标子目录，违反 type-目录一致规则）。"""
    normalized = lint_link_target(slug)
    parts = [p for p in (make_entry_slug(part) for part in normalized.split("/")) if p]
    return f"queries/{parts[-1] if parts else 'missing-page'}.md"


def _stub_title(slug: str) -> str:
    name = _file_name(lint_link_target(slug))
    return re.sub(r"[-_]+", " ", name).strip() or "Missing Page"


def create_stub(knowledge_dir: Path | str, slug: str) -> StubResult:
    """为断链目标创建 type:query stub 条目（REQ-209；幂等，已存在则复用）。

    frontmatter 含 status: open（query 型 schema 要求）与 tags [stub, lint]；
    slug 为断链目标原始串（可含子目录，统一路由 queries/）。
    """
    relative_path = stub_relative_path(slug)
    full_path = Path(knowledge_dir) / relative_path
    if full_path.exists():
        return StubResult(relative_path=relative_path, created=False)
    full_path.parent.mkdir(parents=True, exist_ok=True)
    title = _stub_title(slug)
    today = datetime.now().strftime("%Y-%m-%d")
    content = "\n".join([
        "---",
        "type: query",
        f'title: "{title.replace(chr(34), chr(92) + chr(34))}"',
        f"created: {today}",
        f"updated: {today}",
        "status: open",
        "tags: [stub, lint]",
        "related: []",
        "sources: []",
        "---",
        "",
        f"# {title}",
        "",
        "由 lint 自动创建的占位条目（断链目标缺失），补充内容后请将 status 改为 resolved。",
        "",
    ])
    full_path.write_text(content, encoding="utf-8")
    return StubResult(relative_path=relative_path, created=True)


def suggest_link_targets(broken: str, titles: Iterable[str]) -> list[str]:
    """断链候选建议（REQ-209 纯函数核心）。

    对每个候选标题计算 string_similarity，≥0.74 者按分数降序返回，
    上限 64。三种相似度（Levenshtein/同名/包含）恒开，不受 semantic 开关
    影响。
    """
    scored: list[tuple[float, str]] = []
    seen: set[str] = set()
    for title in titles:
        if not title or title in seen:
            continue
        seen.add(title)
        score = string_similarity(broken, title)
        if score >= BROKEN_LINK_SUGGESTION_MIN_SCORE:
            scored.append((score, title))
    scored.sort(key=lambda item: (-item[0], item[1]))
    return [title for _, title in scored[:MAX_SUGGESTION_CANDIDATES]]
