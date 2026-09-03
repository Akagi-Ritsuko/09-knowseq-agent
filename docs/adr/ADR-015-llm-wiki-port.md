---
title: "ADR-015: 编译层移植 llm_wiki（Karpathy LLM Wiki 模式）+ M4 控制台 React 化"
status: accepted
date: 2026-09-02
amends: ADR-008, ADR-010
---

# ADR-015 编译层移植 llm_wiki + M4 控制台 React 化

## 背景

调研 [nashsu/llm_wiki](https://github.com/nashsu/llm_wiki)（GPL v3，v0.6.6）发现其与本项目高度相关：

- **思想同源**：基于 Karpathy "LLM Wiki 模式"——Raw Sources（不可变原始素材）→ Wiki（LLM 生成知识）→ Schema（规则校验）三层，与 KnowSeq "inbox 素材 → 编译层提炼 → knowledge 条目 → 大脑层索引" 的流水线一致。
- **编译层实现成熟**（`src/lib/`，TypeScript）：ingest 两步 CoT（分析→生成）、持久化队列 + 并发 worker（ingest-queue）、并发提交协调（ingest-commit-coordinator）、SHA256 增量缓存（ingest-cache）、内容去重 + embedding 预筛 + 串行合并队列（dedup*）、上下文预算控制（context-budget）、CJK/文档清洗（ingest-parse/sanitize）、多供应商 LLM 路由（llm-client/llm-providers/llm-task-routing，chat/ingest 模型分离）、wikilink 增强、结构化 lint + 修复、人工审核（review-store，FNV-1a 内容稳定 ID）。这些正是 T-009 要自研的全部难点。
- **展示层组件可复用**（`src/components/`，React 19 + TS + Vite）：wiki 知识库浏览/编辑（index.md、log.md、`[[wikilink]]`、YAML frontmatter，Obsidian 兼容）、图谱可视化（sigma.js + graphology + ForceAtlas2，graph-relevance 四信号相关性排序、Louvain 社区发现、graph-insights 意外连接/知识缺口）。
- **插件可参考**（`extension/`，Chrome MV3 剪藏扩展，对接本地 `clip_server.rs`）。

**用户决策**（2026-09-02，AskUserQuestion 确认）：

1. **分发计划 = 个人自用，不分发** → GPL v3 义务不触发，可以移植/翻译其代码。
2. **展示层路线 = 控制台升级 React，直接移植组件** → 修订 ADR-010 的前端部分。

## 决策

1. **M2 编译层：移植 llm_wiki ingest 内核为 Python `app/compile/`**。移植对象：ingest 两步 CoT、ingest-queue（持久化队列 + worker 生命周期）、ingest-commit-coordinator、ingest-cache（SHA256 增量缓存）、dedup 系列、context-budget、ingest-parse/sanitize（CJK 清洗）、llm-client/llm-providers/llm-task-routing（多供应商路由）、enrich-wikilinks、lint 系列、review-store。**保留 KnowSeq 自有部分**：inbox 素材模型适配（write_material/frontmatter/`compiled` 标记，ADR-013）、四类条目 schema（决策/教训/概念/连接，ADR-008；2026-09-03 修订为五类，新增疑问 Query）、config 体系、FastAPI 触发接口。
2. **M4 展示层：控制台升级 React 19 + Vite + TypeScript，移植 llm_wiki 组件**。复制其 wiki 展示/知识库浏览组件与图谱组件（sigma.js + graphology + ForceAtlas2）；graph-relevance 四信号、Louvain 社区、graph-insights 作为 M3/M4 增强参考。**FastAPI 后端不变**。本决策修订 ADR-010：原"Vue3 或纯 HTML+CDN，M4 定稿"作废，图谱组件选型落定 sigma.js 系（原 vis-network/ECharts 备选不再采用）。
3. **插件：参考 `extension/`（Chrome MV3）**。剪藏交互与打包方式参考之，通信协议改接 KnowSeq FastAPI 网页抓取/手动导入端点（ADR-007、REQ-108/109 延伸），替代其 `clip_server.rs`。
4. **合规边界**：参考源码本地化于 `reference/llm_wiki`（`.gitignore` 已排除，不进仓库、不随项目分发）；移植文件头部注明 `Ported from nashsu/llm_wiki (GPL-3.0)`，保留原归属。**仅限个人自用不分发；任何未来分发前必须重评估许可**（整体 GPL v3 开源，或对相关模块 clean-room 重写）。
5. **ADR-009 LightRAG 大脑层不变**：移植范围仅编译层与展示层。

## 备选方案与理由

- **Clean-room 重写（只看行为不看代码）**：合规最稳，但周期长、细节质量差 → 用户明确要求移植，且个人自用场景下无 GPL 义务。
- **保持 ADR-010 原轻量自研前端，llm_wiki 仅作思想参考**：无法满足"展示部分直接复制"的诉求，重复造轮子。
- **外挂 llm_wiki 为独立服务经 API 调用**：引入 Tauri/Rust + Node 运行时依赖，与 KnowSeq 数据模型（五类条目/REQ 体系）不互通，运维复杂 → 不选。

## 后果

- TS/Rust → Python 是**移植**（语义等价转换：生命周期/并发模型改写为 Python 线程 + 队列），不是复制粘贴；移植时以行为对齐为准。
- React 19 + Vite 引入 Node 构建链，M4 前置 Node LTS；开发态 `vite dev` 代理到 FastAPI，产物由 FastAPI 静态托管。
- `knowledge/` 条目结构（Markdown + wikilinks + frontmatter）与 llm_wiki Wiki 层天然兼容，Obsidian 打开能力保留。
- 风险：GPL 传染仅在未来分发时触发，需长期记住该边界（本 ADR 与 tasks.md 已留痕）。

## 关联

- 关联里程碑：M2、M4
- 关联任务：T-009（经 T-114 细分）、T-011（经 T-115 细分）、T-114、T-115、T-116
- 相关 ADR：ADR-008（编译层，实现参考补充）、ADR-010（前端部分被本 ADR 修订）、ADR-007（网页抓取）、ADR-013（inbox 模型）、ADR-009（大脑层，不变）
- 需求：FR-010、FR-011、FR-030、FR-031、FR-040~042
