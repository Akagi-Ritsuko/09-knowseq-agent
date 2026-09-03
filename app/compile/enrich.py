# Ported from nashsu/llm_wiki (GPL-3.0) src/lib/enrich-wikilinks.ts
"""enrich-wikilinks：为知识条目正文补充指向既有条目的 [[wikilink]]（REQ-212）。

移植自 nashsu/llm_wiki (GPL-3.0) `src/lib/enrich-wikilinks.ts`，保留其 v2 核心设计：
LLM 只返回 ``{"links": [{"term", "target"}]}`` 替换清单，由代码执行字符串替换——
正文在 ``[[ ]]`` 之外字节不变，frontmatter 不被模型触碰，模型幻觉/改写无法破坏页面。

与原版的差异（KnowSeq 适配）：
1. 原版为单页 enrich（保存钩子调用 ``enrichWithWikilinks(projectPath, filePath)``）；
   本版 ``enrich_wikilinks`` 按 REQ-212 遍历全库五类条目，仅手动触发，无后台自动。
2. 额外同步 frontmatter ``related`` 字段：正文新插入链接的目标并入 related
   （复用 dedup.py 移植的 sources-merge.ts 数组工具），保证"related 字段与正文
   链接一致且目标均存在"（REQ-212 验收）。原版只改正文、不动 frontmatter。
3. ``dry_run`` 语义为 KnowSeq 新增：只计算变更并报告，不写任何文件。
4. prompt 中文化；原版 ``buildLanguageDirective`` 大段语言指令省略——term 必须
   逐字取自正文、target 必须命中索引，语言漂移空间已被格式契约消除。
5. temperature/max_tokens 显式固定（0.2/2048）；原版沿用全局 LLM 默认。
6. 磁盘扫描（``extract_entity_summary`` + slug 校验）是唯一权威边界；
   prompt 中注入的索引仅作上下文，与原版一致。
7. ``_find_unlinked`` 修正原版潜在缺陷：原版只查 idx 前 2 字符是否 ``[[``，
   无法拦下已有链接 alias 段内的出现（``[[transformer|Transformer]]`` 会被
   再次链接成嵌套 ``[[transformer|[[Transformer]]]]``）；本版判断 idx 是否
   落在 ``[[`` 与其 ``]]`` 区间内。
   （自链排除原为评审加码，验收确认后回归源码语义——不做自链排除。）
"""

from __future__ import annotations

import json
import re
import unicodedata
from dataclasses import dataclass, field
from pathlib import Path

from .dedup import (
    _extract_first_json_object,
    _merge_lists,
    _parse_frontmatter_array,
    _write_frontmatter_array,
    extract_entity_summary,
)

ENRICH_TEMPERATURE = 0.2
ENRICH_MAX_TOKENS = 2_048

# frontmatter 段定位（含闭合 --- 与其后的换行），兼容 CRLF
_FM_RE = re.compile(r"\A---\r?\n[\s\S]*?\r?\n---(?:\r?\n|$)")

ENRICH_SYSTEM_PROMPT = """你负责找出知识条目正文中应当成为 [[wikilink]]、指向既有知识条目的术语。

你将收到：
  - 知识库索引，列出现有条目（按类型分区，每行形如 `- [[条目名]] 标题`）
  - 一个条目的正文

返回一个 JSON 对象，列出正文中哪些术语应链接到哪个索引条目。

响应格式（必须严格是如下 JSON 结构，不得输出其他任何内容）：
{
  "links": [
    { "term": "正文中逐字出现的文本", "target": "索引中的条目名" }
  ]
}

规则：
- 每个 "term" 必须是正文逐字出现的子串（区分大小写）。
- 每个 "target" 必须是索引中列出的条目。
- 每个 target 至多一条（在首次提及处链接）。
- 只收录明确匹配的术语（例如正文出现 "Transformer" 而索引有 "transformer"，target="transformer" 即正确）。
- 若没有应链接的术语，返回 {"links": []}。
- 严禁输出前言、解释或 markdown 代码围栏——只输出 JSON 对象本身。

## 知识库索引
{index}"""


@dataclass(frozen=True)
class _LinkEntry:
    """LLM 建议的一条替换（term 已校验，target 已归一为磁盘权威 slug）。"""

    term: str
    target: str


@dataclass
class EnrichChange:
    """单个条目的变更报告（dry_run 与真实运行共用）。"""

    path: str  # knowledge 相对路径
    slug: str
    added_related: list[str]  # 新并入 frontmatter related 的目标 slug
    links: list[str]  # 正文实际插入的 wikilink 文本


@dataclass
class EnrichResult:
    """enrich_wikilinks 结果。changes 即报告：dry_run 时未落盘。"""

    scanned: int
    dry_run: bool
    changes: list[EnrichChange] = field(default_factory=list)


def enrich_wikilinks(
    knowledge_dir: Path, ctx, *, dry_run: bool = False
) -> EnrichResult:
    """遍历全库条目，LLM 建议正文 wikilink，校验目标存在后写入正文与 related。

    手动触发（REQ-212）：不做后台自动。每个条目一次 LLM 调用；磁盘扫描所得
    slug 集合是唯一权威边界，索引仅作 prompt 上下文（模型编造/翻译的目标
    一律丢弃），避免重新引入断链。
    """
    kd = Path(knowledge_dir)
    summaries = extract_entity_summary(kd)
    slugs_by_key = _canonical_slugs(summaries)
    index_context = _build_index_context(summaries)
    result = EnrichResult(scanned=len(summaries), dry_run=dry_run)
    for item in summaries:
        entry_path = kd / item["path"]
        try:
            content = entry_path.read_text(encoding="utf-8")
        except OSError:
            continue
        raw = _ask_llm(ctx, index_context, content)
        links = _validate_links(_parse_link_response(raw), slugs_by_key)
        if not links:
            continue
        new_content, targets, texts = _apply_links(content, links)
        if not targets:
            continue
        # REQ-212：正文新链接的目标并入 frontmatter related（与正文链接一致）
        existing = _parse_frontmatter_array(content, "related")
        union = _merge_lists(existing, targets)
        added = [t for t in union if t not in existing]
        if added:
            new_content = _write_frontmatter_array(new_content, "related", union)
        if not dry_run:
            try:
                entry_path.write_text(new_content, encoding="utf-8")
            except OSError:
                continue
        result.changes.append(
            EnrichChange(
                path=item["path"], slug=item["slug"], added_related=added, links=texts
            )
        )
    return result


# ──────────────────────────────────────────────────────────────────
# 权威 slug 集合（enrich-wikilinks.ts collectWikiPageSlugs / normalizeTargetSlug）
# ──────────────────────────────────────────────────────────────────


def _norm_key(text: str) -> str:
    """slug 归一键：NFKC + 去首尾空白 + 小写。"""
    return unicodedata.normalize("NFKC", text).strip().lower()


def _normalize_target(target: str) -> str:
    """归一 LLM 给出的 target：剥 alias/锚点、取文件名、去 .md 后缀。"""
    without_alias = target.split("|", 1)[0].split("#", 1)[0]
    name = without_alias.replace("\\", "/").rsplit("/", 1)[-1]
    name = re.sub(r"\.md$", "", name, flags=re.IGNORECASE)
    return _norm_key(name)


def _canonical_slugs(summaries: list[dict]) -> dict[str, str]:
    """归一键 → 权威 slug；同一键对应多个真实文件（大小写/Unicode 等价共存）时
    歧义放弃，不凭空替读者选择。"""
    candidates: dict[str, set[str]] = {}
    for s in summaries:
        candidates.setdefault(_norm_key(s["slug"]), set()).add(s["slug"])
    return {k: next(iter(v)) for k, v in candidates.items() if len(v) == 1}


def _build_index_context(summaries: list[dict]) -> str:
    """按类型分区构造索引上下文（格式与 indexer 一致：``- [[slug]] title``）。"""
    by_type: dict[str, list[dict]] = {}
    for s in summaries:
        by_type.setdefault(s["type"], []).append(s)
    lines: list[str] = []
    for category in sorted(by_type):
        lines.append(f"## {category}")
        for s in by_type[category]:
            lines.append(f"- [[{s['slug']}]] {s['title']}")
    return "\n".join(lines)


# ──────────────────────────────────────────────────────────────────
# LLM 调用与响应解析（parseLinkResponse 移植，复用 dedup 的 JSON 提取状态机）
# ──────────────────────────────────────────────────────────────────


def _ask_llm(ctx, index_context: str, content: str) -> str:
    system = ENRICH_SYSTEM_PROMPT.replace("{index}", index_context)
    messages = [
        {"role": "system", "content": system},
        {"role": "user", "content": f"页面正文：\n\n{content}"},
    ]
    return ctx.chat(
        messages, temperature=ENRICH_TEMPERATURE, max_tokens=ENRICH_MAX_TOKENS
    )


def _parse_link_response(raw: str) -> list[_LinkEntry]:
    """解析 LLM 响应中的 ``{"links": [...]}``；容错围栏/前言/坏 JSON。"""
    obj = _extract_first_json_object(raw or "")
    if not obj:
        return []
    try:
        parsed = json.loads(obj)
    except json.JSONDecodeError:  # noqa: BLE001 — 模型输出不可信，坏 JSON 静默放弃
        return []
    if not isinstance(parsed, dict) or not isinstance(parsed.get("links"), list):
        return []
    out: list[_LinkEntry] = []
    for item in parsed["links"]:
        if not isinstance(item, dict):
            continue
        term = item.get("term")
        target = item.get("target")
        if isinstance(term, str) and isinstance(target, str) and term and target:
            out.append(_LinkEntry(term=term, target=target))
    return out


def _validate_links(
    links: list[_LinkEntry], slugs_by_key: dict[str, str]
) -> list[_LinkEntry]:
    """target 必须命中磁盘权威 slug（归一匹配），改写为权威形态。

    不做自链排除（与原版一致）：页面正文可能以自身标题词开头，链上自身
    无害，反向链接页仍能正常命中。
    """
    out: list[_LinkEntry] = []
    for link in links:
        canonical = slugs_by_key.get(_normalize_target(link.target))
        if not canonical:
            continue
        out.append(_LinkEntry(term=link.term, target=canonical))
    return out


# ──────────────────────────────────────────────────────────────────
# 替换执行（applyLinks / findUnlinkedOccurrence 移植）
# ──────────────────────────────────────────────────────────────────


def _split_off_frontmatter(content: str) -> tuple[str, str]:
    """剥离 frontmatter（含闭合 --- 与其后换行）；无 frontmatter 返回 ("", 原文)。"""
    m = _FM_RE.match(content)
    if not m:
        return "", content
    return m.group(0), content[m.end():]


def _apply_links(content: str, links: list[_LinkEntry]):
    """把 ``[[ ]]`` 插入正文（frontmatter 之外、每个 target 一次、不在已有链接内）。

    返回 (新内容, 插入的目标 slug 列表, 插入的 wikilink 文本列表)。
    """
    fm, body = _split_off_frontmatter(content)
    linked: set[str] = set()
    targets: list[str] = []
    texts: list[str] = []
    for link in links:
        key = link.target.lower()
        if key in linked:
            continue
        idx = _find_unlinked(body, link.term)
        if idx == -1:
            continue
        if link.term.lower() == link.target.lower():
            text = f"[[{link.term}]]"
        else:
            text = f"[[{link.target}|{link.term}]]"
        body = body[:idx] + text + body[idx + len(link.term):]
        linked.add(key)
        targets.append(link.target)
        texts.append(text)
    return fm + body, targets, texts


def _find_unlinked(body: str, term: str) -> int:
    """term 在正文中首个未包进 ``[[...]]`` 的出现位置；无则 -1。

    原版只检查 idx 前 2 字符窗口是否 ``[[``，拦不住已有链接 alias 段内的出现
    （如 ``[[transformer|Transformer]]`` 中的 alias 会被再次链接产生嵌套）；
    本版改为判断 idx 是否落在某个 ``[[`` 与其 ``]]`` 之间。
    """
    start = 0
    while start < len(body):
        idx = body.find(term, start)
        if idx == -1:
            return -1
        # idx 位于最近的 "[[" 与其闭合 "]]" 之间 → 已有链接内，跳过
        open_idx = body.rfind("[[", 0, idx)
        if open_idx != -1 and body.find("]]", open_idx, idx) == -1:
            start = idx + len(term)
            continue
        return idx
    return -1
