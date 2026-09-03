"""M2 编译层（T-201~214，REQ-201~214 / ADR-008 / ADR-015）。

inbox 素材 → OpenAI 兼容 LLM 两步 CoT → knowledge/ 五类条目
（decision/lesson/concept/connection/query，见 schema.CATEGORIES）。
ingest 内核移植自 nashsu/llm_wiki（GPL-3.0，ADR-015）；条目 schema、触发与
控制台集成为 KnowSeq 自有设计。
"""
from .manager import CompileManager

__all__ = ["CompileManager"]
