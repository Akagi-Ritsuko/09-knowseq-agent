"""五类条目重复检测与合并（T-211 REQ-211）。

Ported from nashsu/llm_wiki (GPL-3.0) —— src/lib/dedup.ts + dedup-runner.ts
+ dedup-storage.ts。与源码的差异：

1. 扫描范围：原版只扫 wiki/entities + wiki/concepts 两类，KnowSeq 按五类
   （decisions/lessons/concepts/connections/queries，ADR-008）全扫。
2. embedding 预筛接口预留（_embedding_prefilter_pairs，默认返回 None=未启用），
   阈值常量 DEDUP_PREFILTER_THRESHOLD=0.68 等参数保留；启用需外部实现向量检索。
3. DETECTOR/MERGER prompt 中文化（与编译层其余 prompt 语言一致），格式契约不变。
4. not-duplicates 白名单落 `.knowseq/dedup-not-duplicates.json`（原 `.llm-wiki/`），
   canonical key 与源码一致（lower → sort → 逗号连接）。
5. index.md 重写：原版保守逐行删除，KnowSeq 复用 indexer.update_index 全量
   重建（indexer 已具备等价能力，格式 `- [[slug]] title`）。
6. I/O 归属：原版纯计算在 dedup.ts、落盘在 dedup-runner.executeMerge；KnowSeq
   无 UI 逐步确认环节，按 REQ-211 签名 merge_duplicate_group 一步完成
   读盘 + 纯计算 + 落盘（备份 → 写 canonical → 引用重写 → 删除 → index 重建），
   纯计算核心 _merge_group_core 独立成函数保持可测。

三阶段（与源码一致，串行单 worker）：
  1. extract_entity_summary —— 纯数据，无 LLM。
  2. detect_duplicate_groups —— LLM 批扫输出 JSON groups（容错解析 +
     白名单过滤 + 无效 slug 过滤）。
  3. merge_duplicate_group —— LLM 正文合并 + 确定性 frontmatter 并集 +
     跨页引用重写 + 备份快照。
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

from .indexer import update_index
from .materials import split_frontmatter
from .schema import CATEGORIES

# ── 与源码一致的容量参数 ──────────────────────────────────────────
DEDUP_DETECTION_MAX_TOKENS = 8_192   # 检测输出上限（有界 JSON 列表）
DEDUP_MERGE_MAX_TOKENS = 16_384      # 合并输出上限（完整页面重写）
DEDUP_PREFILTER_TOP_K = 8            # 预筛每页召回邻居数
DEDUP_PREFILTER_THRESHOLD = 0.68     # 预筛余弦阈值（故意低于"近重复"档）
DEDUP_PREFILTER_MAX_PAGES = 5_000    # 预筛可接受的最大页数
DEDUP_DETECTOR_BATCH_SUMMARIES = 80  # 无预筛批扫每批条数
DEDUP_FALLBACK_BATCH_OVERLAP = 8     # 批间重叠（防边界重复对被拆开）
DEDUP_EMPTY_PREFILTER_FULL_SCAN_LIMIT = 250  # 无预筛时全扫上限，超限返回空（防挂起）

FIELDS_TO_UNION = ("sources", "tags", "related")

_NOT_DUP_FILE = "dedup-not-duplicates.json"


@dataclass
class MergeResult:
    """merge_duplicate_group 的产物（字段对应源码 MergeResult）。

    rewrites：[{"path", "new_content"}]；backup：所有被改文件改动前快照
    [{"path", "content"}]，已同步落 `.knowseq/page-history/dedup-<时间戳>/`。
    """

    canonical_path: str
    canonical_content: str
    rewrites: list = field(default_factory=list)
    pages_to_delete: list = field(default_factory=list)
    backup: list = field(default_factory=list)


# ──────────────────────────────────────────────────────────────────
# 阶段 1：条目摘要（纯数据，无 LLM）
# ──────────────────────────────────────────────────────────────────

def extract_entity_summary(knowledge_dir: Path) -> list[dict]:
    """扫五类目录构建条目摘要列表。解析失败/无 frontmatter 的页面静默跳过。

    path 为 knowledge/ 相对路径（如 `concepts/foo.md`），slug 为 basename 去 .md。
    """
    out: list[dict] = []
    for cat in CATEGORIES:
        cat_dir = knowledge_dir / cat
        if not cat_dir.is_dir():
            continue
        for path in sorted(cat_dir.glob("*.md")):
            try:
                content = path.read_text(encoding="utf-8")
            except OSError:
                continue  # 尽力而为——读不了的页面不参与 dedup
            summary = _extract_one(f"{cat}/{path.name}", content)
            if summary:
                out.append(summary)
    return out


def _extract_one(rel_path: str, content: str) -> dict | None:
    meta, body = split_frontmatter(content)
    if not meta:
        return None
    slug = rel_path.rsplit("/", 1)[-1].removesuffix(".md")
    summary = {
        "slug": slug,
        "path": rel_path,
        "type": _string_field(meta.get("type")) or "unknown",
        "title": _string_field(meta.get("title")) or slug,
        "tags": _array_field(meta.get("tags")),
    }
    description = _string_field(meta.get("description")) or _first_body_paragraph(body)
    if description:
        summary["description"] = _truncate(description, 200)
    return summary


def _string_field(v: object) -> str | None:
    if isinstance(v, str) and v.strip():
        return v.strip()
    return None


def _array_field(v: object) -> list[str]:
    if not isinstance(v, list):
        return []
    return [x for x in v if isinstance(x, str) and x.strip()]


def _first_body_paragraph(body: str) -> str | None:
    """正文首个非空行；跳过标题行与表格行（避免描述只是标题重复或表格噪声）。"""
    for line in body.splitlines():
        line = line.strip()
        if not line:
            continue
        if line.startswith("#") or line.startswith("|"):
            continue
        return line
    return None


def _truncate(s: str, max_len: int) -> str:
    if len(s) <= max_len:
        return s
    return s[: max_len - 1] + "…"


# ──────────────────────────────────────────────────────────────────
# 阶段 2：LLM 批扫检测
# ──────────────────────────────────────────────────────────────────

DETECTOR_SYSTEM_PROMPT = """你是知识库维护助手。你将收到一份知识条目清单。\
请找出"同一主题以不同命名各建了一页"的 slug 分组，例如：

- 同一事物以两种语言命名（英文 vs 中文等）
- 单复数形式（如 "dpao" vs "dpaos"）
- 缩写 vs 全称（如 "vfa" vs "volatile-fatty-acids"）
- 同语言同义词
- 同一专有名词的不同拼写

只输出合法 JSON。不要散文、不要 markdown 代码围栏、JSON 之外不要任何解释。schema：

{
  "groups": [
    {
      "slugs": ["slug-a", "slug-b"],
      "reason": "两者都指 X；前者英文后者中文。",
      "confidence": "high"
    }
  ]
}

规则：
- 只输出 2 个及以上、且都在输入清单中的 slug 分组。
- "high" = 明显同一事物，仅命名不同。
- "medium" = 很可能相同但依赖上下文。
- "low" = 不确定；需人工仔细复核。
- 严禁编造输入清单中不存在的 slug。
- 若没有重复，输出 {"groups": []}。
- type 不同的条目（如 decision 与 concept）通常不应分组——仅在确凿无疑\
指向同一事物时才跨 type 分组。"""


def detect_duplicate_groups(summaries: list[dict], ctx) -> list[dict]:
    """LLM 批扫重复分组。串行；批间重叠防边界重复对被拆开。

    无预筛可用（默认）时：>250 条直接返回空（防挂起，REQ-211）。
    输出已过滤：无效 slug、不足 2 条的组、not-duplicates 白名单组、跨批复重。
    """
    if len(summaries) < 2:
        return []
    not_dup = load_not_duplicates(ctx.knowledge_dir)
    pairs = _embedding_prefilter_pairs(summaries, ctx)
    if pairs is None:
        if len(summaries) > DEDUP_EMPTY_PREFILTER_FULL_SCAN_LIMIT:
            return []
        return _detect_in_batches(summaries, ctx, not_dup)
    if not pairs:
        return []
    if not_dup:
        not_set = {_normalize_group_key(g) for g in not_dup}
        pairs = [p for p in pairs if _normalize_group_key(list(p)) not in not_set]
    if not pairs:
        return []
    involved = {slug for pair in pairs for slug in pair}
    sub = [s for s in summaries if s["slug"] in involved]
    return _detect_in_batches(sub, ctx, not_dup) if len(sub) >= 2 else []


def _embedding_prefilter_pairs(summaries: list[dict], ctx) -> list[tuple[str, str]] | None:
    """embedding 预筛接口（REQ-211 预留，默认关）。

    返回 None = 未启用 → 走全扫/上限路径；返回 pair 列表 = 只扫涉及页面；
    返回空列表 = 有预筛但无候选 → 按上限规则处理（>250 返回空，≤250 全扫）。
    启用需外部提供向量检索实现（top_k=DEDUP_PREFILTER_TOP_K、
    threshold=DEDUP_PREFILTER_THRESHOLD、max_pages=DEDUP_PREFILTER_MAX_PAGES）。
    """
    return None


def _detect_in_batches(summaries: list[dict], ctx, not_dup: list[list[str]]) -> list[dict]:
    if len(summaries) <= DEDUP_DETECTOR_BATCH_SUMMARIES:
        return _detect_batch(summaries, ctx, not_dup)
    # 标题+slug 排序让疑似别名相邻，同时限制每次 LLM 请求规模。
    ordered = sorted(summaries, key=lambda s: (s["title"], s["slug"]))
    stride = DEDUP_DETECTOR_BATCH_SUMMARIES - DEDUP_FALLBACK_BATCH_OVERLAP
    groups: list[dict] = []
    for start in range(0, len(ordered), stride):
        batch = ordered[start : start + DEDUP_DETECTOR_BATCH_SUMMARIES]
        if len(batch) < 2:
            break
        groups.extend(_detect_batch(batch, ctx, not_dup))
    return _unique_groups(groups)


def _detect_batch(summaries: list[dict], ctx, not_dup: list[list[str]]) -> list[dict]:
    messages = [
        {"role": "system", "content": DETECTOR_SYSTEM_PROMPT},
        {"role": "user", "content": _detector_user_message(summaries)},
    ]
    raw = ctx.chat(messages, temperature=0.1, max_tokens=DEDUP_DETECTION_MAX_TOKENS)
    parsed = _parse_detector_response(raw)
    valid = {s["slug"] for s in summaries}
    not_set = {_normalize_group_key(g) for g in not_dup}
    out: list[dict] = []
    for g in parsed:
        slugs = [s for s in g["slugs"] if s in valid]
        if len(slugs) < 2 or _normalize_group_key(slugs) in not_set:
            continue
        out.append({"slugs": slugs, "reason": g["reason"], "confidence": g["confidence"]})
    return out


def _detector_user_message(summaries: list[dict]) -> str:
    lines = []
    for s in summaries:
        tag = f" [{', '.join(s['tags'])}]" if s.get("tags") else ""
        desc = f" — {s['description']}" if s.get("description") else ""
        title = json.dumps(s["title"], ensure_ascii=False)
        lines.append(f"- type={s['type']}, slug={s['slug']}, title={title}{tag}{desc}")
    return (
        f"## 待扫描的知识条目（共 {len(summaries)} 条）\n\n"
        + "\n".join(lines)
        + "\n\n仅返回重复分组 JSON。"
    )


def _parse_detector_response(raw: str) -> list[dict]:
    """容错解析：提取首个配平 `{...}` 并校验。任何失败返回 []。"""
    json_text = _extract_first_json_object(raw)
    if not json_text:
        return []
    try:
        parsed = json.loads(json_text)
    except (json.JSONDecodeError, ValueError):
        return []
    if not isinstance(parsed, dict):
        return []
    groups_raw = parsed.get("groups")
    if not isinstance(groups_raw, list):
        return []
    out: list[dict] = []
    for g in groups_raw:
        if not isinstance(g, dict):
            continue
        slugs_raw = g.get("slugs")
        slugs = [s for s in slugs_raw if isinstance(s, str)] if isinstance(slugs_raw, list) else []
        if len(slugs) < 2:
            continue
        reason_raw = g.get("reason")
        reason = reason_raw if isinstance(reason_raw, str) else ""
        conf_raw = g.get("confidence")
        confidence = conf_raw if conf_raw in ("high", "medium") else "low"
        out.append({"slugs": slugs, "reason": reason, "confidence": confidence})
    return out


def _extract_first_json_object(text: str) -> str | None:
    """从任意文本中提取首个大括号配平的 `{...}` 子串（字符串感知状态机）。"""
    start = text.find("{")
    if start < 0:
        return None
    depth, in_string, escape = 0, False, False
    for i in range(start, len(text)):
        ch = text[i]
        if escape:
            escape = False
            continue
        if ch == "\\":
            escape = True
            continue
        if ch == '"':
            in_string = not in_string
            continue
        if in_string:
            continue
        if ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                return text[start : i + 1]
    return None


def _normalize_group_key(slugs) -> str:
    """分组 canonical key：lower → sort → 逗号连接（与源码 dedup.ts 一致）。"""
    return ",".join(sorted(s.lower() for s in slugs))


def _unique_groups(groups: list[dict]) -> list[dict]:
    seen: set[str] = set()
    out: list[dict] = []
    for g in groups:
        key = _normalize_group_key(g["slugs"])
        if key in seen:
            continue
        seen.add(key)
        out.append(g)
    return out


# ──────────────────────────────────────────────────────────────────
# not-duplicates 白名单（dedup-storage.ts 移植）
# ──────────────────────────────────────────────────────────────────

def _not_duplicates_path(knowledge_dir: Path) -> Path:
    return knowledge_dir.parent / ".knowseq" / _NOT_DUP_FILE


def load_not_duplicates(knowledge_dir: Path) -> list[list[str]]:
    """读白名单。损坏/非数组/元素非字符串列表一律按空处理。"""
    try:
        raw = _not_duplicates_path(knowledge_dir).read_text(encoding="utf-8")
    except OSError:
        return []
    try:
        parsed = json.loads(raw)
    except (json.JSONDecodeError, ValueError):
        return []
    if not isinstance(parsed, list):
        return []
    return [g for g in parsed if isinstance(g, list) and all(isinstance(s, str) for s in g)]


def add_not_duplicate(knowledge_dir: Path, slugs: list[str]) -> None:
    """把"确认不是重复"的组记入白名单（幂等：任意顺序/大小写等价即跳过）。"""
    if len(slugs) < 2:
        return
    lst = load_not_duplicates(knowledge_dir)
    norm_new = _normalize_group_key(slugs)
    if any(_normalize_group_key(g) == norm_new for g in lst):
        return
    lst.append(sorted(slugs))
    path = _not_duplicates_path(knowledge_dir)
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(lst, ensure_ascii=False, indent=2), encoding="utf-8")
    except OSError:  # noqa: BLE001 —— 白名单写失败不影响主流程
        pass


# ──────────────────────────────────────────────────────────────────
# 阶段 3：合并确认的重复组
# ──────────────────────────────────────────────────────────────────

MERGER_SYSTEM_PROMPT = """你是知识库维护助手。你将收到若干页面，它们都被确认描述\
同一实体或概念的不同命名版本。请将它们合并为一个连贯的知识页。

输出完整合并后的文件（frontmatter + 正文）。响应的第一个字符必须是 "-"（即 \
"---" 的开头）。不要前言，不要文件内容之外的任何解释。

规则：
- 保留每个输入页面中每一条不同的事实断言。
- 消除冗余（同一内容不要在多个小节重复出现）。
- 重组小节结构，使其服务于统一后的主题，而不是输入的简单拼接。
- 正文中输入用了 [[wikilink]] 的地方保持该语法。
- Frontmatter：保留标准字段（type, title, created, updated, tags, related, \
sources）。sources/tags/related/updated 之后由调用方做确定性并集覆盖——\
你只需产出合理的正文与合理的 frontmatter 结构。
- 选择最具描述性的标题。若输入使用不同语言，优先采用与正文主体内容一致的\
语言。"""


def merge_duplicate_group(group: dict, ctx) -> MergeResult:
    """合并一个重复组并落盘（备份 → 写 canonical → 引用重写 → 删除 → index 重建）。

    group 为 detect_duplicate_groups 输出的一项（{"slugs", "reason", "confidence"}），
    可带可选 "canonical_slug"（缺省取 slugs[0]）。slug 不在磁盘上时抛 ValueError。
    """
    slugs = [s for s in (group.get("slugs") or []) if isinstance(s, str)]
    if len(slugs) < 2:
        raise ValueError("merge_duplicate_group 需要 2 条以上条目")
    canonical_slug = group.get("canonical_slug") or slugs[0]
    if canonical_slug not in slugs:
        raise ValueError(f"canonical_slug {canonical_slug!r} 不在 group 中：{slugs}")

    knowledge = ctx.knowledge_dir
    pages = _load_pages_by_slug(knowledge)
    group_pages: list[dict] = []
    for slug in slugs:
        hit = pages.get(slug)
        if hit is None:
            raise ValueError(
                f'slug "{slug}" 在磁盘上不存在——检测与合并之间该条目可能已被删除'
            )
        group_pages.append({"slug": slug, "path": hit[0], "content": hit[1]})

    group_paths = {p["path"] for p in group_pages}
    other_pages = [
        {"path": rel, "content": content}
        for slug, (rel, content) in pages.items()
        if rel not in group_paths
    ]

    result = _merge_group_core(group_pages, canonical_slug, other_pages, ctx)
    _persist_merge(result, knowledge)
    return result


def _load_pages_by_slug(knowledge_dir: Path) -> dict[str, tuple[str, str]]:
    """扫五类目录全部 .md：slug → (knowledge 相对路径, 内容)。

    同名 basename 后者覆盖（与源码 loadAllWikiPages 的 pathBySlug 语义一致）。
    """
    pages: dict[str, tuple[str, str]] = {}
    for cat in CATEGORIES:
        cat_dir = knowledge_dir / cat
        if not cat_dir.is_dir():
            continue
        for path in sorted(cat_dir.glob("*.md")):
            try:
                content = path.read_text(encoding="utf-8")
            except OSError:
                continue
            pages[path.stem] = (f"{cat}/{path.name}", content)
    return pages


def _merge_group_core(
    group_pages: list[dict],
    canonical_slug: str,
    other_pages: list[dict],
    ctx,
) -> MergeResult:
    """纯计算（对应源码 mergeDuplicateGroup）：LLM 合并 + 确定性收尾，不碰磁盘。"""
    canonical = next(p for p in group_pages if p["slug"] == canonical_slug)

    # 1. LLM 正文合并
    messages = [
        {"role": "system", "content": MERGER_SYSTEM_PROMPT},
        {"role": "user", "content": _merger_user_message(group_pages)},
    ]
    llm_out = ctx.chat(messages, temperature=0.1, max_tokens=DEDUP_MERGE_MAX_TOKENS)
    if not llm_out.strip():
        # 最小守卫：空输出落盘会毁掉 canonical，直接失败让调用方感知。
        raise ValueError("LLM 合并输出为空，放弃合并")

    # 2. frontmatter 并集（对 LLM 输出的确定性后处理）
    merged = llm_out
    for page in group_pages:
        merged = _merge_array_fields_into_content(merged, page["content"], FIELDS_TO_UNION)

    # 3. updated 盖章为当天
    now = ctx.now or datetime.now()
    merged = _set_frontmatter_scalar(merged, "updated", now.strftime("%Y-%m-%d"))

    # 4. 跨页引用重写：被并 slug → canonical
    redirects = {p["slug"]: canonical_slug for p in group_pages if p["slug"] != canonical_slug}
    rewrites: list[dict] = []
    for page in other_pages:
        rewritten = _rewrite_cross_references(page["content"], redirects)
        if rewritten != page["content"]:
            rewrites.append({"path": page["path"], "new_content": rewritten})

    # 5. 备份：所有被改文件改动前的内容
    backup = [{"path": p["path"], "content": p["content"]} for p in group_pages]
    for r in rewrites:
        orig = next((p for p in other_pages if p["path"] == r["path"]), None)
        if orig:
            backup.append({"path": orig["path"], "content": orig["content"]})

    # 6. 待删除：组内除 canonical 外的页面
    pages_to_delete = [p["path"] for p in group_pages if p["slug"] != canonical_slug]

    return MergeResult(
        canonical_path=canonical["path"],
        canonical_content=merged,
        rewrites=rewrites,
        pages_to_delete=pages_to_delete,
        backup=backup,
    )


def _merger_user_message(group_pages: list[dict]) -> str:
    sections = [
        f"## 第 {i + 1} 页（slug: {p['slug']}）\n\n{p['content']}\n"
        for i, p in enumerate(group_pages)
    ]
    return (
        f"以下 {len(group_pages)} 个页面已被确认为同一主题的不同版本。"
        f'请将它们合并为一个连贯页面（canonical slug 为 "{group_pages[0]["slug"]}"'
        "或调用方指定者）。\n\n"
        + "\n---\n\n".join(sections)
        + "\n\n现在输出合并后的文件。第一个字符必须是 `-`。"
    )


def _persist_merge(result: MergeResult, knowledge_dir: Path) -> None:
    """落盘：备份快照 → 写 canonical → 写引用重写 → 删除被并页 → index 重建。

    备份失败直接抛出（无快照不改动磁盘）；删除失败静默（备份仍在）。
    """
    runtime = knowledge_dir.parent / ".knowseq"
    stamp = datetime.now().isoformat().replace(":", "-").replace(".", "-")
    backup_dir = runtime / "page-history" / f"dedup-{stamp}"
    backup_dir.mkdir(parents=True, exist_ok=True)
    for b in result.backup:
        sanitized = b["path"].replace("/", "_").replace("\\", "_")
        (backup_dir / sanitized).write_text(b["content"], encoding="utf-8")

    (knowledge_dir / result.canonical_path).write_text(
        result.canonical_content, encoding="utf-8")
    for r in result.rewrites:
        (knowledge_dir / r["path"]).write_text(r["new_content"], encoding="utf-8")
    for dead in result.pages_to_delete:
        try:
            (knowledge_dir / dead).unlink()
        except OSError:  # noqa: BLE001 —— 删除失败仅告警，备份仍安全
            pass

    update_index(knowledge_dir)  # 全量重建，被并条目自然消失


# ──────────────────────────────────────────────────────────────────
# frontmatter 数组工具（sources-merge.ts 移植）
# ──────────────────────────────────────────────────────────────────

def _parse_frontmatter_array(content: str, field_name: str) -> list[str]:
    """按字段名提取 frontmatter 数组，兼容 inline 与 block 两种形式。缺省返回 []。"""
    m = re.match(r"^---\r?\n([\s\S]*?)\r?\n---", content)
    if not m:
        return []
    fm = m.group(1)
    name = re.escape(field_name)
    block = re.search(
        rf"^{name}:\s*\r?\n((?:[ \t]+-\s+.+(?:\r?\n|$))+)", fm, re.MULTILINE)
    if block:
        out: list[str] = []
        for line in block.group(1).splitlines():
            lm = re.match(r'^\s+-\s+["\']?(.+?)["\']?\s*$', line)
            if lm and lm.group(1):
                out.append(lm.group(1).strip())
        return out
    inline = re.search(rf"^{name}:\s*\[([^\]]*)\]", fm, re.MULTILINE)
    if not inline:
        return []
    body = inline.group(1).strip()
    if not body:
        return []
    return _split_inline_array(body)


def _split_inline_array(body: str) -> list[str]:
    """行内数组拆分（引号感知：支持单双引号与反斜杠转义）。"""
    out: list[str] = []
    cur: list[str] = []
    quote: str | None = None
    escaped = False
    for ch in body:
        if escaped:
            cur.append(ch)
            escaped = False
            continue
        if quote == '"' and ch == "\\":
            escaped = True
            continue
        if ch in "\"'" and quote is None:
            quote = ch
            continue
        if quote is not None and ch == quote:
            quote = None
            continue
        if ch == "," and quote is None:
            value = "".join(cur).strip()
            if value:
                out.append(value)
            cur = []
            continue
        cur.append(ch)
    value = "".join(cur).strip()
    if value:
        out.append(value)
    return out


def _write_frontmatter_array(content: str, field_name: str, values: list[str]) -> str:
    """重写（或追加）frontmatter 数组字段，统一输出 inline 形式。其余行保持原样。"""
    m = re.match(r"^(---\r?\n)([\s\S]*?)(\r?\n---)", content)
    if not m:
        return content
    open_d, fm_body, close_d = m.group(1), m.group(2), m.group(3)
    newline = "\r\n" if open_d.endswith("\r\n") else "\n"
    name = re.escape(field_name)
    serialized = ", ".join(_quote_inline(v) for v in values)
    new_line = f"{field_name}: [{serialized}]"

    inline_re = re.compile(rf"^{name}:\s*\[[^\]]*\]", re.MULTILINE)
    if inline_re.search(fm_body):
        rewritten = inline_re.sub(lambda _m: new_line, fm_body, count=1)
        return f"{open_d}{rewritten}{close_d}{content[m.end():]}"

    bm = re.search(
        rf"^{name}:\s*\r?\n((?:[ \t]+-\s+.+(?:\r?\n|$))+)", fm_body, re.MULTILINE)
    if bm:
        tail = newline if re.search(r"\r?\n$", bm.group(0)) else ""
        rewritten = fm_body[: bm.start()] + new_line + tail + fm_body[bm.end() :]
        return f"{open_d}{rewritten}{close_d}{content[m.end():]}"

    # 字段缺失 → 追加到 frontmatter 末尾
    rewritten = f"{fm_body}{newline}{new_line}"
    return f"{open_d}{rewritten}{close_d}{content[m.end():]}"


def _quote_inline(value: str) -> str:
    return '"' + value.replace("\\", "\\\\").replace('"', '\\"') + '"'


def _merge_lists(existing: list[str], incoming: list[str]) -> list[str]:
    """并集合并：大小写不敏感去重，首见大小写胜出。"""
    seen: set[str] = set()
    out: list[str] = []
    for s in [*existing, *incoming]:
        key = s.lower()
        if key in seen:
            continue
        seen.add(key)
        out.append(s)
    return out


def _merge_array_fields_into_content(
    new_content: str, existing_content: str | None, fields
) -> str:
    """把磁盘上已有值的数组字段折叠进新内容（并集），返回重写后的新内容。"""
    if not existing_content:
        return new_content
    if not re.match(r"^---\r?\n", existing_content):
        return new_content
    result = new_content
    changed = False
    for field_name in fields:
        old_values = _parse_frontmatter_array(existing_content, field_name)
        if not old_values:
            continue
        new_values = _parse_frontmatter_array(result, field_name)
        merged = _merge_lists(old_values, new_values)
        if merged == new_values:
            continue
        result = _write_frontmatter_array(result, field_name, merged)
        changed = True
    return result if changed else new_content


# ──────────────────────────────────────────────────────────────────
# 引用重写工具（dedup.ts 移植）
# ──────────────────────────────────────────────────────────────────

def _rewrite_cross_references(content: str, redirects: dict[str, str]) -> str:
    """重写正文 wikilink（保 alias）与 frontmatter related 数组（改写 + 去重）。"""
    out = content
    for old_slug, new_slug in redirects.items():
        pat = re.compile(rf"\[\[{re.escape(old_slug)}(\|[^\]]+)?\]\]")
        out = pat.sub(lambda m, ns=new_slug: f"[[{ns}{m.group(1) or ''}]]", out)

    existing = _parse_frontmatter_array(out, "related")
    if existing:
        rewritten = [redirects.get(s, s) for s in existing]
        unique = _merge_lists([], rewritten)  # 大小写不敏感去重，保持顺序
        if len(unique) != len(existing) or any(
            a != b for a, b in zip(unique, existing)
        ):
            out = _write_frontmatter_array(out, "related", unique)
    return out


def _set_frontmatter_scalar(content: str, field_name: str, value: str) -> str:
    r"""行级替换（或追加）frontmatter 标量字段；同名字段已是数组时不触碰（防误伤）。"""
    m = re.match(r"^(---\n)([\s\S]*?)(\n---)", content)
    if not m:
        return content
    open_d, fm_body, close_d = m.group(1), m.group(2), m.group(3)
    name = re.escape(field_name)
    new_line = f"{field_name}: {value}"
    line_re = re.compile(rf"^{name}:([^\n]*)", re.MULTILINE)
    m2 = line_re.search(fm_body)
    if m2 and m2.group(1).lstrip().startswith("["):
        return content
    if m2:
        rewritten = fm_body[: m2.start()] + new_line + fm_body[m2.end():]
        return f"{open_d}{rewritten}{close_d}{content[m.end():]}"
    return f"{open_d}{fm_body}\n{new_line}{close_d}{content[m.end():]}"
