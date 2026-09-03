"""大脑层（M3，LightRAG 封装）。

对 knowledge/ 构建向量索引 + 知识图谱 + 引用溯源（REQ-301~305）。
对外提供同步门面 BrainEngine（内部专用事件循环线程，见 engine.py D1）。
"""
from .engine import BrainEngine

__all__ = ["BrainEngine"]
