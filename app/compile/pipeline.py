"""编译管线：两步 CoT 编排 + 长源分块 + 落盘与 index/log 维护（T-207 / T-208 REQ-207/208）。

Ported from nashsu/llm_wiki (GPL-3.0) —— src/lib/ingest.ts 的 autoIngest 主流程、
buildAnalysisPrompt / buildGenerationPrompt / buildReviewSuggestionPrompt /
buildTruncatedFileRepairPrompt、writeFileBlocks 与截断修复。

与原实现差异：
- Prompt 整体中文化（KnowSeq 面向中文知识库），小节结构与指令顺序忠实原文；
- 九类 wiki → 五类 schema（ADR-008）：无 sources 摘要页与 entities 目录，
  "What to generate" 由 source summary page 改为按路由表产出条目页；
- 同名条目冲突不做 LLM body merge，改为 stem-2/-3 后缀让多次编译共存
  （P3 决策：零新依赖 + 确定性优先）；
- 语言守卫简化为 zh 专用 CJK 占比启发式（原 detectLanguage + CJK 兼容集合）；
- LLM 无可用产出时 fallback 记 log.md 单行摘要，不落条目页（REQ-207）；
- 完整性门禁：硬失败或截断未恢复时 raise CompileIncompleteError，交给
  manager 的队列语义重试（原实现由缓存层读取 hardFailures 数组决定不写缓存）；
- 取消用 threading.Event（不引 asyncio），检查点对齐原文 throwIfIngestAborted；
- 字符制预算不引 tokenizer（P3 决策），max_tokens 分档沿用原常量表。
"""

from __future__ import annotations

import re
import threading
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Callable

import yaml

from ..config import Config
from .blocks import (
    ParseResult,
    filter_repair_blocks,
    parse_file_blocks,
    parse_review_blocks,
    should_run_dedicated_review_stage,
)
from .cache import sha256_text
from .context_budget import DEFAULT_MAX_CTX, compute_budget, compute_source_budget
from .filename import make_entry_slug
from .indexer import append_log, update_index
from .llm_client import stream_chat
from .long_source import (
    LongSourcePlan,
    analyze_long_source,
    clear_checkpoint,
    compute_chunk_params,
    split_source_into_semantic_chunks,
    trim_long_text,
)
from .materials import split_frontmatter
from .sanitize import sanitize_document
from .schema import CATEGORY_BY_TYPE, CATEGORIES, PURPOSE, SCHEMA

# --- token 预算（对齐原 INGEST_GENERATION_TOKENS_* 常量与分档函数） ---

GENERATION_TOKENS_DEFAULT = 8_192
GENERATION_TOKENS_128K = 16_384
GENERATION_TOKENS_256K = 24_576
GENERATION_TOKENS_512K = 32_768
GENERATION_TIERS = ((512_000, GENERATION_TOKENS_512K), (256_000, GENERATION_TOKENS_256K), (128_000, GENERATION_TOKENS_128K))

STEP1_TEMPERATURE = 0.1
STEP1_MAX_TOKENS = 4_096

ENTRY_PREFIX = "knowledge/"
LOG_PATH = "knowledge/log.md"
INDEX_PATH = "knowledge/index.md"
# 产物记录基准：相对 knowledge_dir（cache.files_written 约定，存在性检查 root / f）
LOG_REL = "log.md"
INDEX_REL = "index.md"

# --- 语言守卫（zh 专用启发式；原文 detectLanguage + CJK 兼容集合） ---

_LANGUAGE_SAMPLE_CHARS = 1_500
_LANGUAGE_MIN_SAMPLE = 20
_ZH_CJK_RATIO = 0.15
_CJK_RE = re.compile(r"[\u4e00-\u9fff]")
_CODE_FENCE_RE = re.compile(r"```[\s\S]*?```")
_BLOCK_MATH_RE = re.compile(r"\$\$[\s\S]*?\$\$")
_INLINE_MATH_RE = re.compile(r"\$[^$\n]*\$")
_WHITESPACE_RE = re.compile(r"\s+")
_FALLBACK_SUMMARY_MAX = 2_000
_CONFLICT_SUFFIX_MAX = 1000

_TRUNCATED_WARNING_PREFIX = "FILE 块未闭合（缺少 ---END FILE---）："

_LANG_NAMES = {"zh": "中文", "en": "英文", "ja": "日文", "ko": "韩文"}


class _NoAliasDumper(yaml.SafeDumper):
    """禁用 anchor/alias：同一 date 对象重复出现时保持字面值样式（frontmatter 可读性）。"""

    def ignore_aliases(self, data):
        return True


class CompileIncompleteError(RuntimeError):
    """编译完整性门禁失败：存在写入硬失败或截断未恢复的 FILE 块。

    manager 捕获后按队列语义重试；不写缓存、不 mark_compiled。
    """


class CompileCancelled(RuntimeError):
    """用户取消编译（cancel_event 置位）。"""


def compute_generation_max_tokens(max_context_size: int | None) -> int:
    """按上下文档位取生成 max_tokens（对齐原 computeIngestGenerationMaxTokens）。"""
    max_ctx = compute_budget(max_context_size).max_ctx
    for threshold, tokens in GENERATION_TIERS:
        if max_ctx >= threshold:
            return tokens
    return GENERATION_TOKENS_DEFAULT


def compute_review_max_tokens(max_context_size: int | None) -> int:
    """review 专职阶段预算（对齐原 computeIngestReviewMaxTokens）。"""
    return min(8_192, max(4_096, compute_generation_max_tokens(max_context_size) // 2))


@dataclass
class PipelineContext:
    """一次编译的运行上下文。

    llm_fn 供测试/脚本注入假 LLM（签名 (messages, *, temperature, max_tokens) -> str）；
    缺省走 stream_chat（OpenAI 兼容流式，Key 不落日志）。now 注入用于确定性测试。
    """

    config: Config
    knowledge_dir: Path
    runtime_dir: Path
    content: str
    source_identity: str
    cancel_event: threading.Event | None = None
    llm_fn: Callable[..., str] | None = None
    now: datetime | None = None

    def chat(self, messages: list[dict], *, temperature: float, max_tokens: int) -> str:
        if self.llm_fn is not None:
            return self.llm_fn(messages, temperature=temperature, max_tokens=max_tokens)
        return stream_chat(
            self.config,
            messages,
            overrides={"temperature": temperature, "max_tokens": max_tokens},
            stop_event=self.cancel_event,
        ).content


@dataclass
class CompileOutcome:
    """compile_one 的成功产物。files 为 knowledge/ 相对路径（含 index/log）。"""

    files: list[str] = field(default_factory=list)
    reviews: list = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)


def _language_directive(output_language: str) -> str:
    """强制输出语言指令（对齐原 buildLanguageDirective；未知语言不注入）。"""
    name = _LANG_NAMES.get(output_language)
    if not name:
        return ""
    return "\n".join(
        [
            f"## ⚠️ 强制输出语言：{name}",
            "",
            f"环境散文用 **{name}** 书写。",
            f"所有生成的散文（含散文标题与小节标题）必须是{name}。",
            "不要翻译、转写或描述专名与技术标识符，除非素材已使用广泛通行的本地化形式。",
            "组织名、产品名、模型名、数据集名、工具/库名、缩写、代码标识符、文件名、URL、"
            "论文标题、引用串以及没有广泛通行本地化译名的技术术语，保留其标准原形。",
            f"素材或库内容可能是其他语言；把它作为证据使用，但生成的散文保持{name}。",
            "本语言规则覆盖较弱的风格指令，但不覆盖上方的专名与技术标识符保留规则。",
        ]
    )


def _content_matches_language(content: str) -> bool:
    """zh 专用语言守卫：样本 CJK 占比 ≥ 0.15 才放行（对齐原 contentMatchesTargetLanguage）。"""
    sample = split_frontmatter(content)[1]
    sample = _INLINE_MATH_RE.sub("", _BLOCK_MATH_RE.sub("", _CODE_FENCE_RE.sub("", sample)))
    sample = sample.strip()[:_LANGUAGE_SAMPLE_CHARS]
    if len(sample) < _LANGUAGE_MIN_SAMPLE:
        return True
    cjk = len(_CJK_RE.findall(sample))
    return cjk / len(sample) >= _ZH_CJK_RATIO


def _stamp_entry(content: str, source_identity: str, today: str) -> str:
    """条目 stamp：created/updated 归一为 today + sources 确保含来源。

    合并原 stampGeneratedFrontmatterDates 与 canonicalizeSourcesField 为
    一次 frontmatter 解析/回写（原文三次正则/解析操作等价改写）。
    """
    meta, body = split_frontmatter(content)
    # date 对象让 safe_dump 输出无引号的 ISO 日期（对齐原正则替换后的样式）
    today_date = datetime.strptime(today, "%Y-%m-%d").date()
    meta["created"] = today_date
    meta["updated"] = today_date
    sources = meta.get("sources")
    if isinstance(sources, str):
        sources = [sources]
    if not isinstance(sources, list):
        sources = []
    normalized = [str(s).strip() for s in sources if str(s).strip()]
    if source_identity not in normalized:
        normalized.append(source_identity)
    meta["sources"] = normalized
    dumped = yaml.dump(
        meta, Dumper=_NoAliasDumper, allow_unicode=True,
        default_flow_style=False, sort_keys=False, width=10**9)
    return "---\n" + dumped + "---\n" + body


def _stamp_log_date(content: str, today: str) -> str:
    """log 块日期归一：YYYY-MM-DD 占位符与已有具体日期都替换为 today。

    合并原文两步（占位符替换 + 首个 ## [date] 行替换）为双 sub（超集行为）。
    """
    text = re.sub(r"\bYYYY-MM-DD\b", today, content)
    return re.sub(r"\b\d{4}-\d{2}-\d{2}\b", today, text)


def _routing_issue(rel_path: str, content: str) -> str | None:
    """schema 路由校验（对齐原 validateWikiPageRouting）：目录 ∈ 五类且与 type 一致。"""
    parts = rel_path.split("/")
    if len(parts) != 3 or not parts[2].endswith(".md"):
        return "路径必须为 knowledge/<category>/<slug>.md 形式"
    category = parts[1]
    if category not in CATEGORIES:
        return f"目录 {category} 不在五类路由表内"
    meta, _ = split_frontmatter(content)
    ftype = str(meta.get("type", "")).strip().lower()
    if CATEGORY_BY_TYPE.get(ftype) != category:
        return f"frontmatter type {ftype or '(缺失)'} 与目录 {category} 不一致"
    return None


def _resolve_conflict(knowledge_dir: Path, sub: str) -> str:
    """同名条目冲突改 stem-2/-3 后缀（KnowSeq 以确定性改写替代原 LLM body merge）。"""
    if not (knowledge_dir / sub).exists():
        return sub
    base = Path(sub)
    for i in range(2, _CONFLICT_SUFFIX_MAX + 1):
        candidate = base.with_name(f"{base.stem}-{i}{base.suffix}")
        if not (knowledge_dir / candidate).exists():
            return candidate.as_posix()
    return sub  # 放弃改写走覆盖（极端情形）


@dataclass
class _WriteResult:
    """_write_blocks 产物。

    completed_input 保留模型请求的原始路径：冲突改写只影响最终落盘路径，
    截断修复按"模型请求的路径"匹配是否恢复（对齐原文 completedInputPaths 语义）。
    hard_failures = 有意写入但被文件系统拒绝的块（区别于内容级软拒收）。
    """

    written: list[str] = field(default_factory=list)
    completed_input: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    hard_failures: list[str] = field(default_factory=list)
    truncated: list[str] = field(default_factory=list)


def _write_blocks(
    ctx: PipelineContext,
    result: ParseResult,
    *,
    source_identity: str,
    today: str,
    language_guard: bool,
) -> _WriteResult:
    """逐块落盘（对齐原 writeFileBlocks 三分支：log 追加 / index 拒收 / 条目写）。

    流程：sanitize → log 用 _stamp_log_date、条目用 _stamp_entry → 路由校验
    → 语言守卫 → 冲突改写 → 写盘；FS 错误计入 hard_failures 不中断后续块。
    """
    out = _WriteResult(truncated=list(result.truncated_paths),
                       warnings=list(result.warnings))  # 解析警告并入（原文 1901-1902）
    for block in result.blocks:
        _check_cancel(ctx)
        rel = block.path  # parse_file_blocks 已做反斜杠归一
        if rel == INDEX_PATH:
            out.warnings.append(f'忽略模型产出的 "{rel}"；聚合索引由应用确定性维护。')
            continue

        content = sanitize_document(block.content)
        is_log = rel == LOG_PATH
        if is_log:
            content = _stamp_log_date(content, today)
        else:
            content = _stamp_entry(content, source_identity, today)
            issue = _routing_issue(rel, content)
            if issue:
                out.warnings.append(f'Dropped "{rel}" — {issue}')
                continue
            if language_guard and not _content_matches_language(content):
                out.warnings.append(f'Dropped "{rel}" — 正文语言与目标输出语言不符。')
                continue

        try:
            if is_log:
                # log.md 追加式合并（KnowSeq 归一尾换行，避免累积空行）
                log_path = ctx.knowledge_dir / "log.md"
                existing = ""
                if log_path.exists():
                    existing = log_path.read_text(encoding="utf-8")
                if existing.strip():
                    log_path.write_text(
                        existing.rstrip("\n") + "\n\n" + content.strip() + "\n", encoding="utf-8")
                else:
                    log_path.write_text(content.strip() + "\n", encoding="utf-8")
                final = LOG_REL
            else:
                sub = _resolve_conflict(ctx.knowledge_dir, rel[len(ENTRY_PREFIX):])
                full_path = ctx.knowledge_dir / sub
                full_path.parent.mkdir(parents=True, exist_ok=True)
                full_path.write_text(content, encoding="utf-8")
                final = sub
            out.written.append(final)
            out.completed_input.append(block.path)
        except OSError as exc:
            out.warnings.append(f'写入 "{rel}" 失败：{exc}')
            out.hard_failures.append(rel)
    return out


# --- Step 1 分析 prompt（对齐原 buildAnalysisPrompt，中文改编） ---


def build_analysis_prompt(
    purpose: str,
    index: str,
    source_context: str = "",
    schema: str = "",
    language_directive: str = "",
) -> str:
    """两步 CoT 的第一步：读源素材产出结构化分析（"讨论"步）。"""
    return "\n".join(
        line
        for line in [
            "你是一名资深研究分析员。阅读源素材并产出结构化分析。",
            "不要输出思维链、隐藏推理或思考过程记录。在内部推理，只写出简洁的最终分析。",
            "",
            language_directive,
            "",
            "你的分析应覆盖：",
            "",
            "## 关键实体",
            "列出素材中提到的人物、组织、产品、数据集、工具。对每一个给出：",
            "- 名称与类型",
            "- 在素材中的角色（核心 vs. 外围）",
            "- 是否可能已存在于知识库（检查索引）",
            "",
            "## 关键概念",
            "列出理论、方法、技术、现象。对每一个给出：",
            "- 名称与简要定义",
            "- 它在本素材中为何重要",
            "- 是否可能已存在于知识库",
            "",
            "## 主要论断与发现",
            "- 核心主张或结果是什么？",
            "- 有什么证据支持？",
            "- 证据强度如何？",
            "- 每条主张说的是哪个具名主体？不要因为关键词相同就把一条主张、"
            "限制或评价从一个实体/模型/产品/方法转移到另一个。",
            "- 素材中的结构化数据要逐字保留进分析：SQL DDL / CREATE TABLE 语句、"
            "schema 定义、API 签名、配置与表格放进 fenced code block 或 Markdown 表格。"
            "不要把确切的字段名、类型、约束、键、索引化成散文。",
            "",
            "## 与既有知识库的关联",
            "- 本素材与哪些既有条目相关？",
            "- 它是加强、挑战还是扩展了既有知识？",
            "",
            "## 矛盾与张力",
            "- 素材中是否有与知识库既有内容冲突之处？",
            "- 素材内部是否有张力或保留意见？",
            "",
            "## 建议",
            "- 应创建或更新哪些知识库条目？",
            "- 若项目 schema（见下）定义了五类之外的条目类型，且素材确有对应内容，"
            "推荐相应类型的页面——显式指明类型。仅当素材确实支持；"
            "绝不发明素材中不存在的条目。",
            "- 哪些内容应强调、哪些应弱化？",
            "- 有哪些值得向用户标记的开放问题？",
            "",
            "要全面但简洁。聚焦真正重要的内容。",
            "",
            "若提供了目录上下文，把它作为分类提示——目录结构通常反映用户的组织意图"
            "（如 'papers/energy' 说明该文件是一篇能源相关论文）。",
            "",
            f"## 项目 Schema（可用条目类型——素材内容契合时映射到 schema 定义的类型）\n{schema}"
            if schema
            else "",
            f"## 知识库定位（背景）\n{purpose}" if purpose else "",
            f"## 当前知识库索引（用于检查既有内容）\n{index}" if index else "",
        ]
        if line
    )


# --- Step 2 生成 prompt（对齐原 buildGenerationPrompt，中文改编；无 sources 摘要页） ---


def build_generation_prompt(
    schema: str,
    purpose: str,
    index: str,
    source_identity: str,
    source_context: str = "",
    language_directive: str = "",
    today: str = "",
) -> str:
    """两步 CoT 的第二步：基于分析产出 FILE/REVIEW 块（输出格式必须是最后一节）。"""
    return "\n".join(
        line
        for line in [
            "你是一名知识库维护员。根据提供的分析，生成知识库文件。",
            "不要输出思维链、隐藏推理或解释性开场白。在内部推理，只输出要求的 FILE/REVIEW 块。",
            "",
            language_directive,
            "",
            "## 重要：源素材",
            f"原始源素材是：**{source_identity}**",
            "从该素材生成的所有知识库条目，其 frontmatter `sources` 字段必须包含此标识。",
            f"今天的日期是 **{today}**。所有新建条目的 `created`、`updated` 与 log 的 ingest 日期"
            "都使用这个确切日期。",
            "",
            "## 项目 Schema 与路由（AUTHORITATIVE）",
            schema,
            "",
            "以此 schema 作为条目类型与目录的首要路由规则。",
            "每张生成条目的 frontmatter type 必须与其 FILE 路径中使用的 schema 目录一致。",
            "",
            "## 要生成什么",
            "",
            "1. 按上方路由表为分析识别的关键事物产出条目页：决策入 decisions/、"
            "经验教训入 lessons/、概念/方法/技术/抽象入 concepts/、跨条目关联入 connections/。"
            "拿不准类型时优先 concept。",
            "2. query 类型条目（开放问题/待研究项）写入 queries/，frontmatter 必须含 `status: open`。",
            "3. 在正文用 [[wikilink]] 语法做条目间交叉引用。",
            "4. 为 knowledge/log.md 生成一条追加条目（只要新条目本身，格式："
            f"`- [{today}] ingest | 标题`）。",
            "不要生成 knowledge/index.md。聚合索引由应用确定性维护，"
            "大知识库绝不通过模型输出整体重写。",
            "",
            "## Frontmatter 规则（CRITICAL——解析器是严格的）",
            "",
            "每张条目以 YAML frontmatter 块开始。格式规则按重要性排序：",
            "",
            "1. 文件的第一行必须恰好是 `---`（三个连字符，没有其他内容）。",
            "   不要把文件包进 ```yaml ... ``` 代码栅栏。",
            "   不要以 `frontmatter:` 键或任何其他行开头。",
            "2. frontmatter 每行是一个独立的 `key: value` 对。",
            "3. frontmatter 以另一行独立的 `---` 结束。",
            "4. 收尾 `---` 的下一行是正文开始。",
            "5. 数组用标准 YAML 行内形式 `[a, b, c]`（每项外不再加括号）。",
            "   Wikilink 只属于正文——绝不要写 `related: [[a]], [[b]]`（非法 YAML）；",
            "   写 `related: [a, b]`，用裸 slug。",
            "",
            "必填字段与类型：",
            "  • type     — 五类之一（decision | lesson | concept | connection | query）",
            "  • title    — 字符串（含冒号时加引号，如 `title: \"Foo: Bar\"`）",
            f"  • created  — {today}（新条目，YYYY-MM-DD，不加引号）",
            f"  • updated  — {today}（与 created 相同）",
            "  • tags     — 裸字符串数组：`tags: [microbiology, ai]`",
            "  • related  — 裸知识库条目 slug 数组：`related: [foo, bar-baz]`。不要包含",
            "               `knowledge/`、`.md` 或 `[[…]]`——只要 slug。",
            f"  • sources  — 来源标识数组；必须包含 \"{source_identity}\"。",
            "  • status   — 仅 query 条目：`open` 或 `resolved`（新建一律 `open`）。",
            "",
            "一张完整、可解析条目的具体示例（两行 `---` 之间是 frontmatter；",
            "下方的标题与散文是正文）：",
            "",
            "    ---",
            "    type: concept",
            "    title: 示例条目",
            f"    created: {today}",
            f"    updated: {today}",
            "    tags: [example, demo]",
            "    related: [related-slug-1, related-slug-2]",
            f"    sources: [\"{source_identity}\"]",
            "    ---",
            "",
            "    # 示例条目",
            "",
            "    正文内容写在这里。交叉引用在正文使用 [[wikilink]] 语法。",
            "",
            "其他规则：",
            "- 条目间交叉引用在正文使用 [[wikilink]] 语法",
            "- 保持主体边界：当素材讨论多个实体/模型/产品/方法时，"
            "把主张、评价、限制、基准结果与建议绑定在它们所描述的确切主体上。",
            "- 不要仅因术语相同（如上下文窗口大小、基准名、数据集、架构或特性名）"
            "就把关于一个主体的主张合并或泛化进另一个主体的条目。",
            "- 若条目需要为对比提及另一主体，显式写成对比，并注明支持该表述的来源"
            "（frontmatter `sources` 条目）。",
            "- 拉丁文文件名用 kebab-case；中日韩标题保留 CJK 字符"
            "（不要罗马化为拼音/罗马字，也不要译成英文）。",
            "- 专名与技术标识符优先：OpenAI、GPT-5、Transformer、CLIP、ImageNet、"
            "PyTorch、CUDA、GitHub、arXiv、React 等名称保留标准原形；"
            "不要把原始 URL、引用串或完整论文标题直接放进文件路径，"
            "把周围的描述性散文转成安全可读的标题。",
            "- 结构化数据逐字保留：把 SQL DDL / CREATE TABLE 语句、schema 定义、API 签名、"
            "配置与表格数据以 fenced code block（或 Markdown 表格）复制进条目，而不是改述。"
            "确切的列名、类型、约束、主/外键与索引必须在编译中存活——"
            "丢掉它们的纯散文摘要会毁掉用户导入该素材想保留的结构。",
            "- 遵循分析中关于强调什么的建议",
            "- 若分析发现了与既有条目的关联，添加交叉引用",
            "",
            "## REVIEW 块类型",
            "",
            "所有 FILE 块之后，为任何需要人工判断的事项选择性输出 REVIEW 块：",
            "",
            "- contradiction: 分析发现与知识库既有内容冲突",
            "- duplicate: 某实体/概念可能以不同名称已存在于索引",
            "- missing-page: 某重要概念被引用但没有专属条目",
            "- suggestion: 进一步研究、相关素材来源、值得探索的关联",
            "",
            "只为真正需要人工输入的事项创建 review。不要创建琐碎的 review。",
            "",
            "## OPTIONS 允许的值（只有这些预定义标签）：",
            "",
            "- contradiction: OPTIONS: Create Page | Skip",
            "- duplicate: OPTIONS: Create Page | Skip",
            "- missing-page: OPTIONS: Create Page | Skip",
            "- suggestion: OPTIONS: Create Page | Skip",
            "",
            "不要发明自定义选项标签。只使用 'Create Page' 与 'Skip'。",
            "",
            "对 suggestion 与 missing-page review，SEARCH 字段必须包含 2-3 条网页搜索查询",
            "（关键词丰富、具体、适合搜索引擎——不是标题或句子）。示例：",
            "  SEARCH: automated technical debt detection AI generated code | software quality metrics LLM code generation | static analysis tools agentic software development",
            "",
            f"## 知识库定位\n{purpose}" if purpose else "",
            f"## 当前知识库索引（保留全部既有条目，添加新条目）\n{index}" if index else "",
            "",
            # ── 输出格式必须是最后一节——模型对最近指令权重最高 ──
            "## 输出格式（必须严格遵守——解析器按此读取你的响应）",
            "",
            "你的整个响应由 FILE 块加可选的 REVIEW 块组成。没有其他内容。",
            "",
            "FILE 块模板：",
            "```",
            "---FILE: knowledge/<category>/<slug>.md---",
            "（含 YAML frontmatter 的完整文件内容）",
            "---END FILE---",
            "```",
            "",
            "REVIEW 块模板（可选，在所有 FILE 块之后）：",
            "```",
            "---REVIEW: type | 标题---",
            "说明需要用户注意什么。",
            "OPTIONS: Create Page | Skip",
            "PAGES: knowledge/page1.md, knowledge/page2.md",
            "SEARCH: query 1 | query 2 | query 3",
            "---END REVIEW---",
            "```",
            "",
            "## 输出要求（STRICT——偏离将导致解析失败）",
            "",
            "1. 响应的第一个字符必须是 `-`（`---FILE:` 的开头）。",
            "2. 不要输出任何开场白，如 \"以下是文件：\"、\"基于分析……\" 或任何引子散文。",
            "3. 不要复述或重述分析——那是 Stage 1 的工作。你的工作是输出 FILE 块。",
            "4. 不要在 FILE/REVIEW 块之外输出 Markdown 表格、列表或标题。",
            "5. 不要在最后一个 `---END FILE---` 或 `---END REVIEW---` 之后输出任何尾随评论。",
            "6. 块之间只用空行——没有散文。",
            "7. FILE 块的散文（正文、解释、描述、小节文本）必须使用下方规定的强制输出语言。"
            "专名、缩写、模型名、数据集名、工具/库名、代码标识符、URL、文件名、"
            "引用串、论文标题以及没有广泛通行本地化等价物的技术术语，"
            "保留其标准原形——包括在条目名与小节标题中。",
            "",
            "若你以 `---FILE:` 以外的任何内容开头，整个响应将被丢弃。",
            "",
            # 在最末尾重复语言指令，使其赢得"最近指令"决胜。中小模型否则会
            # 对个别条目漂移回训练数据语言。
            "---",
            "",
            language_directive,
        ]
        if line
    )


# --- review 专职阶段 prompt（对齐原 buildReviewSuggestionPrompt，中文改编） ---


def build_review_suggestion_prompt(
    purpose: str,
    index: str,
    source_identity: str,
    analysis: str,
    source_context: str,
    generation: str,
    max_context_size: int | None,
    language_directive: str = "",
) -> str:
    """Step 2 之后的专职 review 阶段：只为未解决知识缺口输出 REVIEW 块。"""
    section_cap = max(4_000, int(compute_budget(max_context_size).max_ctx * 0.15))
    index_cap = max(3_000, int(section_cap * 0.8))
    return "\n".join(
        line
        for line in [
            "你在为个人知识库识别高价值的后续研究项。",
            "不要输出思维链、隐藏推理或解释性开场白。",
            "",
            language_directive,
            "",
            "你的任务不是生成知识库条目。条目生成已经完成。",
            "只为值得人工关注或深度研究的未解决知识缺口输出 REVIEW 块。",
            "",
            "只为真正有用的后续工作创建 REVIEW 块：",
            "- missing-page: 某重要实体/概念被引用但仍缺专属条目",
            "- suggestion: 能实质性改进知识库的研究问题、素材类型或对比",
            "- contradiction: 需要用户判断的冲突或张力",
            "- duplicate: 疑似重复的条目/名称，需要用户复核",
            "",
            "优先产出 1-5 条高信号 review。若没有值得 review 的内容，输出为空。",
            "对 suggestion 与 missing-page review，包含一行 SEARCH，"
            "内含 2-3 条关键词丰富的网页搜索查询，以 ` | ` 分隔。",
            "只使用这些选项：OPTIONS: Create Page | Skip",
            "",
            "REVIEW 块模板：",
            "```",
            "---REVIEW: suggestion | 精确标题---",
            "缺口是什么、为何重要的简要描述。",
            "OPTIONS: Create Page | Skip",
            "PAGES: knowledge/page1.md, knowledge/page2.md",
            "SEARCH: query 1 | query 2 | query 3",
            "---END REVIEW---",
            "```",
            "",
            "只返回 REVIEW 块。不要输出 FILE 块。不要把响应包进 markdown 栅栏。",
            "",
            f"## 知识库定位\n{purpose}" if purpose else "",
            f"## 当前知识库索引\n{trim_long_text(index, index_cap)}" if index else "",
            "",
            f"## 源素材\n{source_identity}",
            "",
            "## Stage 1 分析",
            trim_long_text(analysis, section_cap),
            "",
            "## 源素材内容",
            trim_long_text(source_context, section_cap),
            "",
            "## 已生成的知识库输出",
            trim_long_text(generation, section_cap),
        ]
        if line
    )


# --- 截断修复 prompt（对齐原 buildTruncatedFileRepairPrompt，中文改编） ---


def build_truncated_file_repair_prompt(
    paths: list[str],
    source_identity: str,
    schema: str,
    purpose: str,
    analysis: str,
    source_context: str,
    max_context_size: int | None,
    language_directive: str = "",
) -> str:
    """截断修复 system prompt：对每个请求路径恰好返回一个完整 FILE 块。"""
    section_cap = max(4_000, int(compute_budget(max_context_size).max_ctx * 0.12))
    return "\n".join(
        line
        for line in [
            "你在修复此前生成中被截断的知识库 FILE 块。",
            "对每个请求路径恰好返回一个完整 FILE 块，不要输出其他文件。",
            "每个块必须以 `---END FILE---` 结束。不要输出开场白、REVIEW 块或尾随评论。",
            "精确保留请求的路径，并在每个条目的 frontmatter `sources` 字段中包含源素材标识。",
            "",
            language_directive,
            "",
            "## 请求的路径",
            *[f"- {p}" for p in paths],
            "",
            f"## 源素材标识\n{source_identity}",
            f"## 项目 schema\n{trim_long_text(schema, section_cap)}" if schema else "",
            f"## 知识库定位\n{trim_long_text(purpose, section_cap)}" if purpose else "",
            f"## Stage 1 分析\n{trim_long_text(analysis, section_cap)}",
            f"## 源素材内容\n{trim_long_text(source_context, section_cap)}",
        ]
        if line
    )


# --- 消息与杂项辅助 ---


def _check_cancel(ctx: PipelineContext) -> None:
    if ctx.cancel_event is not None and ctx.cancel_event.is_set():
        raise CompileCancelled("编译已被取消")


def _read_index(knowledge_dir: Path) -> str:
    try:
        return (knowledge_dir / "index.md").read_text(encoding="utf-8")
    except OSError:
        return ""


def _step1_user_message(source_identity: str, source_context: str) -> str:
    return f"分析以下源素材：\n\n**文件：** {source_identity}\n\n---\n\n{source_context}"


def _build_step2_user_message(source_identity: str, analysis: str, source_context: str) -> str:
    """Step 2 user 消息（对齐原文 1074-1094 结构，中文改编）。"""
    return "\n".join([
        f"待处理源素材：**{source_identity}**",
        "",
        "下方 Stage 1 分析是供你参考的上下文。不要复述它的表格、要点或散文。",
        "你的输出只能是系统提示规定的 FILE/REVIEW 块——其他内容一律不要。",
        "",
        "## Stage 1 分析（仅作上下文——不要复述）",
        "",
        analysis,
        "",
        "## 源素材",
        "",
        source_context,
        "",
        "---",
        "",
        f"现在为源自 **{source_identity}** 的知识库条目输出 FILE 块。",
        "你的响应必须以 `---FILE:` 作为最开始的字符。",
        "不要任何开场白。不要分析散文。立即开始。",
    ])


def compile_one(ctx: PipelineContext) -> CompileOutcome:
    """编译单个源素材：两步 CoT + review 阶段 + 落盘 + index/log 维护（REQ-207/208）。

    完整性门禁：存在写入硬失败或截断未恢复的 FILE 块时 raise CompileIncompleteError，
    交由 manager 的队列语义重试；此时已写条目保留，checkpoint 不清除。
    """
    files: list[str] = []
    warnings: list[str] = []
    _check_cancel(ctx)
    ctx.knowledge_dir.mkdir(parents=True, exist_ok=True)  # 确定性 index/log 兜底的前提
    today = (ctx.now or datetime.now()).strftime("%Y-%m-%d")
    max_context = int(ctx.config.get("compile.llm.max_context") or DEFAULT_MAX_CTX)
    output_language = str(ctx.config.get("compile.output_language", "") or "")
    language_rule = _language_directive(output_language)
    language_guard = output_language == "zh"

    # 1) 稳定上下文与素材预算
    index_text = _read_index(ctx.knowledge_dir)
    stable = len(SCHEMA) + len(PURPOSE) + len(index_text)
    source_budget = compute_source_budget(max_context, stable)
    source_context = ctx.content

    # 2) 长源分支（超预算才分块；len(chunks)<=1 短路回退）
    plan = LongSourcePlan(chunked=False)
    if len(ctx.content) > source_budget:
        target_chars, overlap_chars = compute_chunk_params(source_budget)
        chunks = split_source_into_semantic_chunks(ctx.content, target_chars, overlap_chars)
        if len(chunks) > 1:
            checkpoint_key = f"{make_entry_slug(Path(ctx.source_identity).stem)}-{sha256_text(ctx.content)[:16]}"
            plan = analyze_long_source(
                chunks, ctx, checkpoint_key=checkpoint_key,
                source_identity=ctx.source_identity, source_hash=sha256_text(ctx.content),
                source_length=len(ctx.content), source_budget=source_budget,
                target_chars=target_chars, overlap_chars=overlap_chars, index=index_text)
    analysis = ""
    if plan.chunked:
        analysis = plan.analysis
        source_context = plan.source_context

    # 3) Step 1（长源已产出分析时跳过，对齐 precomputedAnalysis）
    if not analysis:
        analysis = ctx.chat(
            [
                {"role": "system", "content": build_analysis_prompt(
                    PURPOSE, index_text, source_context, SCHEMA, language_rule)},
                {"role": "user", "content": _step1_user_message(ctx.source_identity, source_context)},
            ],
            temperature=STEP1_TEMPERATURE, max_tokens=STEP1_MAX_TOKENS)

    # 4) Step 2 生成
    generation = ctx.chat(
        [
            {"role": "system", "content": build_generation_prompt(
                SCHEMA, PURPOSE, index_text, ctx.source_identity, source_context,
                language_rule, today)},
            {"role": "user", "content": _build_step2_user_message(
                ctx.source_identity, analysis, source_context)},
        ],
        temperature=STEP1_TEMPERATURE, max_tokens=compute_generation_max_tokens(max_context))

    # 5) dedicated review 阶段（失败吞掉；取消引发的异常上抛）
    review_output = ""
    if should_run_dedicated_review_stage(generation):
        _check_cancel(ctx)
        try:
            review_output = ctx.chat(
                [
                    {"role": "system", "content": build_review_suggestion_prompt(
                        PURPOSE, index_text, ctx.source_identity, analysis, source_context,
                        generation, max_context, language_rule)},
                    {"role": "user", "content": "只输出高价值的 REVIEW 块，用于后续研究或未解决的知识缺口。"
                                                "若没有则什么都不输出。"},
                ],
                temperature=STEP1_TEMPERATURE, max_tokens=compute_review_max_tokens(max_context))
        except Exception:  # noqa: BLE001 —— review 阶段失败不阻断编译（原文 onError 只置标志）
            _check_cancel(ctx)
            review_output = ""

    # 6) 写盘
    write_result = _write_blocks(ctx, parse_file_blocks(generation),
                                 source_identity=ctx.source_identity, today=today,
                                 language_guard=language_guard)
    files.extend(write_result.written)
    warnings.extend(write_result.warnings)
    hard_failures = list(write_result.hard_failures)
    written_set = set(write_result.written)
    unrecovered: list[str] = []
    for p in write_result.truncated:
        if p not in written_set and p not in unrecovered:
            unrecovered.append(p)

    # 7) 截断修复一次（generation 档；recovered 按模型请求路径匹配）
    if unrecovered:
        repair_output = ""
        try:
            repair_output = ctx.chat(
                [
                    {"role": "system", "content": build_truncated_file_repair_prompt(
                        unrecovered, ctx.source_identity, SCHEMA, PURPOSE, analysis,
                        source_context, max_context, language_rule)},
                    {"role": "user", "content": "现在重新生成请求的 FILE 块。以 `---FILE:` 开头立即输出。"},
                ],
                temperature=STEP1_TEMPERATURE, max_tokens=compute_generation_max_tokens(max_context))
        except Exception as exc:  # noqa: BLE001
            _check_cancel(ctx)
            warnings.append(f"截断 FILE 修复失败：{exc}")
        if repair_output.strip():
            kept, filter_warnings = filter_repair_blocks(
                parse_file_blocks(repair_output).blocks, unrecovered)
            warnings.extend(filter_warnings)
            second = _write_blocks(ctx, ParseResult(blocks=kept),
                                   source_identity=ctx.source_identity, today=today,
                                   language_guard=language_guard)
            for p in second.written:
                if p not in written_set:
                    files.append(p)
                    written_set.add(p)
            completed = set(second.completed_input)
            recovered = [p for p in unrecovered if p in completed]
            for p in recovered:
                prefix = _TRUNCATED_WARNING_PREFIX + p
                warnings = [w for w in warnings if not w.startswith(prefix)]
            warnings.extend(second.warnings)
            hard_failures.extend(second.hard_failures)
            recovered_set = set(recovered)
            unrecovered = [p for p in unrecovered if p not in recovered_set]

    # 8) 确定性 index 重建（变更计入 files）+ log 兜底 + fallback 摘要
    try:
        if update_index(ctx.knowledge_dir):
            files.append(INDEX_REL)
    except OSError as exc:
        warnings.append(f"确定性索引更新失败：{exc}")

    if not any(f.lower() == LOG_REL for f in files):
        try:
            if append_log(ctx.knowledge_dir, f"[{today}] ingest | {ctx.source_identity}"):
                files.append(LOG_REL)
        except OSError as exc:
            warnings.append(f"确定性日志更新失败：{exc}")

    content_pages = [f for f in files if f not in (LOG_REL, INDEX_REL)]
    if not content_pages:
        # LLM 产出无条目页时 fallback：记单行摘要，不落条目页（REQ-207）
        summary = _WHITESPACE_RE.sub(" ", analysis).strip()[:_FALLBACK_SUMMARY_MAX]
        try:
            append_log(ctx.knowledge_dir, f"[{today}] fallback | {ctx.source_identity} | {summary}")
        except OSError:
            pass  # non-critical

    # 9) 完整性门禁：硬失败或截断未恢复 → raise（manager 队列重试，不写缓存）
    if hard_failures or unrecovered:
        raise CompileIncompleteError(
            f"编译不完整：{len(hard_failures)} 个文件写入失败（{', '.join(hard_failures)}），"
            f"{len(unrecovered)} 个 FILE 块截断未恢复（{', '.join(unrecovered)}）")

    reviews = parse_review_blocks(generation) + parse_review_blocks(review_output)
    if plan.chunked and plan.checkpoint_path is not None:
        clear_checkpoint(plan.checkpoint_path)
    return CompileOutcome(files=files, reviews=reviews, warnings=warnings)
