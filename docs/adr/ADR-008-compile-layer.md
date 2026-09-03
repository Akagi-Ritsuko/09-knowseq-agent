---
title: "ADR-008: 编译层（云端 LLM 提炼，复用 memory-compiler 思想）"
status: accepted
date: 2026-09-02
---

# ADR-008 编译层

## 背景

`inbox/` 原始素材（屏幕文本、剪贴板、飞书消息、文件、网页）含大量噪音，直接建索引效果差。需要先提炼为结构化知识。

## 决策

- 采用**云端 LLM 提炼流水线**：对 `inbox/` 新增素材，提炼为五类知识条目——**决策（Decision）/ 教训（Lesson）/ 概念（Concept）/ 连接（Connection）/ 疑问（Query）**，写入 `knowledge/`（Markdown + wikilinks，与 memory-compiler 结构兼容，Obsidian 可打开）。
- **疑问（Query）**：素材暴露的开放问题、素材间相互矛盾的待解点，落 `knowledge/queries/`。frontmatter 沿用基础字段（`type/title/created/updated/tags/related/sources`），另加 `status: open | resolved`（默认 `open`）；解决后转化为决策/教训/概念条目并通过 `related` 互链（矛盾处理流程参考 llm_wiki：标注矛盾 → 建 query 追踪 → 链接双方来源 → 解决后转正式条目）。
- **幂等**：以"已提炼标记"记录，重复执行不重复产出（FR-010）。
- 触发：自动（新素材到达/定时）+ 手动（界面按钮）（FR-011）。

## 备选方案与理由

- **让 LightRAG 直接吃原始素材**：原始噪音多，提炼质量差 → 增加编译层。
- **纯规则/关键词提炼**：无法理解语义 → 用云端 LLM。

## 后果

- 消耗云端 API token（M2 需做成本/节流控制，如合并批量提炼）。
- `knowledge/` 成为下游（大脑层）的干净输入，也是用户可读的知识资产。

## 关联

- 关联里程碑：M2
- 关联任务：T-009
- 相关 ADR：ADR-002（采集流水线）、ADR-009（大脑层）
- 修订：ADR-015（实现方式补充——移植 llm_wiki ingest 内核为 `app/compile/`；本 ADR 的目标与幂等要求不变）
- 修订（2026-09-03）：新增第五类条目**疑问（Query）**——原四类无法承载"开放问题/矛盾追踪"场景，此为 llm_wiki 九类页型中唯一真正缺失的页型；其余 llm_wiki 页型仍不引入。ADR-015 及 M2 文档中"四类"表述以本修订为准。
- 需求：FR-010、FR-011
