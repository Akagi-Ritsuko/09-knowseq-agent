---
title: "ADR-009: 大脑层用 LightRAG"
status: accepted
date: 2026-09-02
---

# ADR-009 大脑层

## 背景

需要"向量化 + 知识图谱 + 引用溯源"，且尽量使用现成组件、本地运行。

## 决策

- 采用 **LightRAG**（`lightrag-hku`）作为大脑层：对 `knowledge/` 建立**向量索引 + 自动知识图谱**，支持增量更新、引用溯源，配置 OpenAI 兼容云端 API（LLM + embedding）。
- 通过 LightRAG API 提供检索/问答/图谱数据，供交互层调用。

## 备选方案与理由

- **Microsoft GraphRAG**：功能全但重（建图开销大）→ 不选。
- **自研轻量（sqlite-vec + networkx + LLM 抽实体）**：可控但工期长、图谱质量依赖自研抽取 → 选用成熟的 LightRAG，符合"现成组件"约定。

## 后果

- 增加 LightRAG 依赖（Python 包 + 可能的本地服务进程）。
- 需配置云端 embedding 与 LLM API（NFR-002 Key 本地配置）。

## 关联

- 关联里程碑：M3
- 关联任务：T-010
- 相关 ADR：ADR-008（编译层）、ADR-010（交互层）、ADR-001（技术栈）
- 需求：FR-020、FR-021、FR-022、FR-030
