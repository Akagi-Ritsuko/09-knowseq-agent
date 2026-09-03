"""上下文字符预算分配（T-204 REQ-204）。

Ported from nashsu/llm_wiki (GPL-3.0) —— src/lib/context-budget.ts。
预算单位是字符不是 token（P3 决策，不引 tokenizer）：

    ┌─────────────────────────────────────────────┐
    │              max_ctx (100%)                 │
    ├──────┬───────────────┬──────────┬───────────┤
    │ idx  │    pages      │ 余量     │  resp     │
    │  5%  │     50%       │  ~30%    │   15%     │
    └──────┴───────────────┴──────────┴───────────┘

余量部分不设统一预算（system prompt 固定、history 按条数控制）。
response_reserve 兼作"不得填充上限"与单页截断基准。
"""
from dataclasses import dataclass

DEFAULT_MAX_CTX = 204_800
RESPONSE_RESERVE_FRAC = 0.15
INDEX_BUDGET_FRAC = 0.05
PAGE_BUDGET_FRAC = 0.5
PER_PAGE_FRAC = 0.3
PER_PAGE_FLOOR = 5_000


@dataclass(frozen=True)
class ContextBudget:
    max_ctx: int            # 模型全上下文窗口（字符）
    response_reserve: int   # 留给 LLM 回答，提示词不得占用
    index_budget: int       # 索引摘要预算（~5%，够列全部条目标题）
    page_budget: int        # 可填充的条目内容总预算
    max_page_size: int      # 单条目截断上限


def compute_budget(max_context_size: int | None) -> ContextBudget:
    """非法值（0/None/负数）回退默认 200K 字符。"""
    max_ctx = max_context_size if isinstance(max_context_size, int) and max_context_size > 0 \
        else DEFAULT_MAX_CTX
    response_reserve = int(max_ctx * RESPONSE_RESERVE_FRAC)
    index_budget = int(max_ctx * INDEX_BUDGET_FRAC)
    page_budget = int(max_ctx * PAGE_BUDGET_FRAC)
    # 单页上限：下限 5K（小配置也放得下短条目）、上限不超 page_budget
    # （极小配置下 floor 不得大过总预算）、否则按 30% 线性伸缩
    max_page_size = min(page_budget, max(PER_PAGE_FLOOR, int(page_budget * PER_PAGE_FRAC)))
    return ContextBudget(max_ctx, response_reserve, index_budget, page_budget, max_page_size)


# --- 长源素材预算（T-208 REQ-208，Ported from computeIngestSourceBudget） ---

LONG_SOURCE_MIN_BUDGET = 8_000              # 预算下限（低于此也按 8K 截）
LONG_SOURCE_MAX_SINGLE_PASS_BUDGET = 300_000  # 单遍可承载素材上限


def compute_source_budget(max_context_size: int | None, stable_context_length: int) -> int:
    """单次编译可容纳的素材字符预算（对齐原 computeIngestSourceBudget）。

    从 max_ctx 中扣除：响应预留（15%）、稳定上下文预留
    （min(25%, max(12K, stable))）、指令预留（max(12K, 8%)），
    再夹到 [LONG_SOURCE_MIN_BUDGET, min(300K, 60%·max_ctx)]。
    素材超过该预算时走长源分块编译。
    """
    budget = compute_budget(max_context_size)
    stable_reserve = min(int(budget.max_ctx * 0.25), max(12_000, stable_context_length))
    instruction_reserve = max(12_000, int(budget.max_ctx * 0.08))
    available = budget.max_ctx - budget.response_reserve - stable_reserve - instruction_reserve
    upper = min(
        LONG_SOURCE_MAX_SINGLE_PASS_BUDGET,
        max(LONG_SOURCE_MIN_BUDGET, int(budget.max_ctx * 0.6)),
    )
    return max(LONG_SOURCE_MIN_BUDGET, min(upper, available))
