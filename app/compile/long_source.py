"""长源素材分块编译（T-208 REQ-208）。

Ported from nashsu/llm_wiki (GPL-3.0) —— splitSourceIntoSemanticChunks /
splitOversizedBlock / semanticBlocks / overlapSuffix / analyzeLongSourceInChunks
及其配套 checkpoint 与 chunk 分析双 prompt。

与原实现差异：
- checkpoint 存 <runtime>/compile-checkpoints/<key>.json（原 .llm-wiki/ingest-progress/），
  JSON 键用 snake_case；hash 由调用方用 sha256 截断生成后传入（原 FNV-1a 64bit）；
- analyze_long_source 只负责逐块分析（target/overlap 计算与语义分块拆分导出为
  compute_chunk_params / split_source_into_semantic_chunks，由 pipeline 先行调用），
  返回 LongSourcePlan 而非 CompileOutcome（分析阶段无 files/reviews 可填）；
- digest 小节去掉 Entities（KnowSeq 五类无 entity 页类型），语言指令按
  config.output_language 注入。
"""

from __future__ import annotations

import json
import re
import time
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

from .schema import PURPOSE, SCHEMA

if TYPE_CHECKING:
    from .pipeline import PipelineContext

LONG_SOURCE_CHUNK_MIN = 12_000            # 单 chunk 目标字符下限
LONG_SOURCE_CHUNK_MAX = 60_000            # 单 chunk 目标字符上限
LONG_SOURCE_DIGEST_MAX = 15_000           # 全局 digest 截断上限
LONG_SOURCE_CHUNK_ANALYSIS_MAX = 40_000   # 单 chunk 分析截断上限

CHECKPOINT_VERSION = 1

_HEADING_RE = re.compile(r"^(#{1,6})\s+(.+?)\s*$")
_SENTENCE_PIECE_RE = re.compile(r"[^.!?。！？\n]+[.!?。！？]?|\n+")

TRIM_MARK = "\n\n[...trimmed for prompt budget...]"


@dataclass
class SourceChunk:
    """一个语义分块。index 从 1 起，overlap_before 取上一块尾部。"""

    id: str
    index: int
    total: int
    heading_path: str
    overlap_before: str
    main: str


@dataclass
class LongSourcePlan:
    """长源分析产物：chunked=False 表示无需分块（原文可直接进 Step1）。"""

    chunked: bool
    analysis: str = ""
    source_context: str = ""
    checkpoint_path: Path | None = None


def trim_long_text(text: str, max_chars: int) -> str:
    if len(text) <= max_chars:
        return text
    return text[:max_chars].rstrip() + TRIM_MARK


# --- 语义分块（对齐原 splitSourceIntoSemanticChunks 及其辅助） ---


def split_oversized_block(block: str, target_chars: int) -> list[str]:
    """超长段落（>1.25×target）按句子切分；句子本身超长则硬切片。"""
    if len(block) <= target_chars * 1.25:
        return [block]
    pieces = _SENTENCE_PIECE_RE.findall(block) or [block]
    out: list[str] = []
    current = ""
    for piece in pieces:
        if current and len(current) + len(piece) > target_chars:
            out.append(current.strip())
            current = ""
        if len(piece) > target_chars:
            for i in range(0, len(piece), target_chars):
                part = piece[i : i + target_chars].strip()
                if part:
                    out.append(part)
        else:
            current += piece
    if current.strip():
        out.append(current.strip())
    return out


@dataclass
class _SemanticBlock:
    text: str
    heading_path: str


def semantic_blocks(content: str, target_chars: int) -> list[_SemanticBlock]:
    """标题 + 空行分段为最小语义块，维护标题路径栈。"""
    blocks: list[_SemanticBlock] = []
    heading_stack: list[str] = []
    paragraph: list[str] = []
    paragraph_heading = ""

    def current_heading_path() -> str:
        return " > ".join(h for h in heading_stack if h)

    def flush_paragraph() -> None:
        nonlocal paragraph
        text = "\n".join(paragraph).strip()
        if text:
            for piece in split_oversized_block(text, target_chars):
                blocks.append(_SemanticBlock(piece, paragraph_heading))
        paragraph = []

    for line in content.replace("\r\n", "\n").split("\n"):
        heading = _HEADING_RE.match(line)
        if heading is not None:
            flush_paragraph()
            depth = len(heading.group(1))
            del heading_stack[depth - 1 :]
            heading_stack.append(heading.group(2).strip())
            blocks.append(_SemanticBlock(line.strip(), current_heading_path()))
            paragraph_heading = current_heading_path()
            continue
        if not line.strip():
            flush_paragraph()
            paragraph_heading = current_heading_path()
            continue
        if not paragraph:
            paragraph_heading = current_heading_path()
        paragraph.append(line)
    flush_paragraph()
    return blocks


def overlap_suffix(text: str, max_chars: int) -> str:
    """取 text 尾部至多 max_chars：优先段落边界，其次句子边界，兜底裸切。"""
    if not text or max_chars <= 0:
        return ""
    if len(text) <= max_chars:
        return text
    raw = text[-max_chars:]
    para = re.search(r"\n\s*\n", raw)
    if para is not None and para.start() > 0 and len(raw) - para.start() > max_chars * 0.4:
        return raw[para.start() :].strip()
    sent = re.search(r"[.!?。！？]\s+", raw)
    if sent is not None and sent.start() > 0 and len(raw) - sent.start() > max_chars * 0.4:
        return raw[sent.start() + 1 :].strip()
    return raw.strip()


def split_source_into_semantic_chunks(
    content: str, target_chars: int, overlap_chars: int
) -> list[SourceChunk]:
    """按序聚合语义块至 target（"\\n\\n" 连接），块间带 overlap 前缀。"""
    target = max(1_000, target_chars)
    blocks = semantic_blocks(content, target)
    if not blocks:
        return []

    raw_chunks: list[tuple[str, str]] = []  # (main, heading_path)
    current: list[str] = []
    current_length = 0
    current_heading = blocks[0].heading_path

    def flush() -> None:
        nonlocal current, current_length
        main = "\n\n".join(current).strip()
        if main:
            raw_chunks.append((main, current_heading))
        current = []
        current_length = 0

    for block in blocks:
        next_length = current_length + len(block.text) + (2 if current else 0)
        if current and next_length > target:
            flush()
        if not current:
            current_heading = block.heading_path
        current.append(block.text)
        current_length += len(block.text) + (2 if len(current) > 1 else 0)
    flush()

    return [
        SourceChunk(
            id=f"chunk-{idx + 1}",
            index=idx + 1,
            total=len(raw_chunks),
            heading_path=heading_path,
            overlap_before=overlap_suffix(raw_chunks[idx - 1][0], overlap_chars) if idx > 0 else "",
            main=main,
        )
        for idx, (main, heading_path) in enumerate(raw_chunks)
    ]


def compute_chunk_params(source_budget: int) -> tuple[int, int]:
    """由素材预算推导 chunk 目标与 overlap（对齐原函数开头两行 clamp）。"""
    target = max(LONG_SOURCE_CHUNK_MIN, min(LONG_SOURCE_CHUNK_MAX, int(source_budget * 0.55)))
    overlap = max(800, min(3_000, int(target * 0.08)))
    return target, overlap


# --- checkpoint（对齐原 isCompatible / load / save / clear） ---


def checkpoint_path(runtime_dir: Path, checkpoint_key: str) -> Path:
    return Path(runtime_dir) / "compile-checkpoints" / f"{checkpoint_key}.json"


def _checkpoint_compatible(cp: dict, params: dict) -> bool:
    """参数全等 + completed_through 范围 + analyses 数量一致，任一不满足即弃用。"""
    completed = cp.get("completed_through")
    analyses = cp.get("analyses")
    return (
        cp.get("version") == CHECKPOINT_VERSION
        and cp.get("source_identity") == params["source_identity"]
        and cp.get("source_hash") == params["source_hash"]
        and cp.get("source_length") == params["source_length"]
        and cp.get("source_budget") == params["source_budget"]
        and cp.get("target_chars") == params["target_chars"]
        and cp.get("overlap_chars") == params["overlap_chars"]
        and cp.get("chunk_total") == params["chunk_total"]
        and isinstance(completed, int)
        and 0 <= completed <= params["chunk_total"]
        and isinstance(analyses, list)
        and len(analyses) == completed
    )


def load_checkpoint(path: Path, params: dict) -> dict | None:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    if not isinstance(data, dict) or not _checkpoint_compatible(data, params):
        return None
    return data


def save_checkpoint(path: Path, checkpoint: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(checkpoint, ensure_ascii=False, indent=2), encoding="utf-8")


def clear_checkpoint(path: Path) -> None:
    try:
        path.unlink(missing_ok=True)
    except OSError:  # noqa: BLE001 —— best-effort 清理，残留文件会因参数不匹配被忽略
        pass


# --- 逐块分析（对齐原 extractMarkedSection + chunk 分析双 prompt + 主循环） ---


def extract_marked_section(raw: str, heading: str) -> str:
    pattern = rf"(?:^|\n)##\s+{re.escape(heading)}\s*\n([\s\S]*?)(?=\n##\s|$)"
    match = re.search(pattern, raw, re.IGNORECASE)
    return match.group(1).strip() if match else ""


def build_chunk_analysis_system_prompt(
    schema: str, purpose: str, index: str, output_language: str = ""
) -> str:
    return "\n".join(
        line
        for line in [
            "你正在为个人知识库分析一篇长文档素材。",
            "不要输出思维链、隐藏推理或思考过程。",
            "只分析当前 MAIN CHUNK；overlap 与 digest 仅作上下文参考。",
            "专名与既有知识库条目、前文 digest 保持一致，不要变更译名。",
            output_language and f"- 全部输出使用{output_language}。",
            "",
            "输出恰好两个 Markdown 小节：",
            "",
            "## Chunk Analysis",
            "- 本 chunk 的简明摘要",
            "- 新增或更新的概念（concept 候选）",
            "- 素材真正支持的其他类型候选（decision / lesson / connection / query）",
            "- 断言、发现、证据、矛盾点",
            "- 本 chunk 中的结构化数据（如出现）：SQL DDL / API 签名 / 配置 / 表格"
            "逐字保留在代码块或 Markdown 表格中，保留字段名、类型、约束、键与索引",
            "- 悬而未决的问题或研究空白",
            "",
            "## Updated Global Digest",
            "一份紧凑的全局摘要，纳入本 chunk 内容并保留跨 chunk 上下文。",
            "digest 必须按以下小节组织：Summary、Concepts、Typed Candidates、"
            "Claims、Evidence、Contradictions、Open Questions、Cross-Chunk Relations。",
            "只有素材真正支持时才产出类型化候选；不得编造素材中不存在的 "
            "decision、lesson、query 等记录。",
            "",
            "以下是稳定的项目上下文，很少变化，视为背景即可：",
            purpose and f"## 知识库定位\n{purpose}",
            schema and f"## 知识库 Schema\n{schema}",
            index and f"## 当前知识库索引\n{trim_long_text(index, 40_000)}",
        ]
        if line
    )


def build_chunk_analysis_user_prompt(
    source_identity: str,
    chunk: SourceChunk,
    global_digest: str,
    folder_context: str = "",
) -> str:
    return "\n".join(
        line
        for line in [
            f"Source file: {source_identity}",
            folder_context and f"Folder context: {folder_context}",
            f"Chunk: {chunk.index}/{chunk.total}",
            chunk.heading_path and f"Heading path: {chunk.heading_path}",
            "",
            "## Current Global Digest",
            global_digest or "（暂无前文 digest。）",
            "",
            chunk.overlap_before and "## Previous Overlap Context\n" + chunk.overlap_before,
            "",
            "## MAIN CHUNK TO ANALYZE",
            chunk.main,
            "",
            "只返回要求的两个小节。除非 MAIN CHUNK 支持，不要重复仅出现在 overlap 中的事实。",
        ]
        if line
    )


def analyze_long_source(
    chunks: list[SourceChunk],
    ctx: PipelineContext,
    *,
    checkpoint_key: str,
    source_identity: str,
    source_hash: str,
    source_length: int,
    source_budget: int,
    target_chars: int,
    overlap_chars: int,
    index: str = "",
) -> LongSourcePlan:
    """逐块分析长源素材，checkpoint 断点续跑（对齐原 analyzeLongSourceInChunks）。

    每块后保存进度；全部完成后返回综合 analysis 与 source_context。
    checkpoint 的清除由 pipeline 在编译成功后执行（失败保留以便重试续跑）。
    """
    if len(chunks) <= 1:
        return LongSourcePlan(chunked=False)

    output_language = ctx.config.get("compile.output_language", "") or ""
    system_prompt = build_chunk_analysis_system_prompt(SCHEMA, PURPOSE, index, output_language)
    ckpt_path = checkpoint_path(ctx.runtime_dir, checkpoint_key)
    params = {
        "source_identity": source_identity,
        "source_hash": source_hash,
        "source_length": source_length,
        "source_budget": source_budget,
        "target_chars": target_chars,
        "overlap_chars": overlap_chars,
        "chunk_total": len(chunks),
    }
    saved = load_checkpoint(ckpt_path, params)
    global_digest = str(saved.get("global_digest", "")) if saved else ""
    analyses: list[str] = list(saved.get("analyses", [])) if saved else []
    completed_through = int(saved.get("completed_through", 0)) if saved else 0

    for chunk in chunks:
        if chunk.index <= completed_through:
            continue
        raw = ctx.chat(
            [
                {"role": "system", "content": system_prompt},
                {
                    "role": "user",
                    "content": build_chunk_analysis_user_prompt(
                        source_identity,
                        chunk,
                        trim_long_text(global_digest, LONG_SOURCE_DIGEST_MAX),
                    ),
                },
            ],
            temperature=0.1,
            max_tokens=4096,
        )
        chunk_analysis = extract_marked_section(raw, "Chunk Analysis") or raw.strip()
        next_digest = extract_marked_section(raw, "Updated Global Digest")
        analyses.append(
            "\n".join(
                [
                    f"## Chunk {chunk.index}/{chunk.total}"
                    + (f" — {chunk.heading_path}" if chunk.heading_path else ""),
                    trim_long_text(chunk_analysis, LONG_SOURCE_CHUNK_ANALYSIS_MAX),
                ]
            )
        )
        global_digest = trim_long_text(
            next_digest or "\n\n".join(part for part in (global_digest, chunk_analysis) if part),
            LONG_SOURCE_DIGEST_MAX,
        )
        completed_through = chunk.index
        save_checkpoint(
            ckpt_path,
            {
                "version": CHECKPOINT_VERSION,
                **params,
                "completed_through": completed_through,
                "global_digest": global_digest,
                "analyses": analyses,
                "updated_at": int(time.time() * 1000),
            },
        )

    analysis = "\n".join(
        [
            "# 长文档综合分析（Consolidated）",
            "",
            "## Final Global Digest",
            global_digest or "（未产出 digest。）",
            "",
            "## Per-Chunk Analyses",
            "\n\n".join(analyses),
        ]
    )
    source_context = "\n".join(
        [
            f"# 长源上下文：{source_identity}",
            "",
            f"原始素材已按语义边界切分为 {len(chunks)} 个 chunk（含 overlap）逐块分析。"
            "请以下方综合上下文为准，不要假设原文提前结束。",
            "",
            "## Final Global Digest",
            global_digest or "（未产出 digest。）",
            "",
            "## Chunk Analysis Notes",
            trim_long_text(
                "\n\n".join(analyses), max(source_budget, LONG_SOURCE_CHUNK_ANALYSIS_MAX)
            ),
        ]
    )
    return LongSourcePlan(
        chunked=True, analysis=analysis, source_context=source_context, checkpoint_path=ckpt_path
    )
