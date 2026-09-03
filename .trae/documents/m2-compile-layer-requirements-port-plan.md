# M2 编译层移植规划：需求拆分 + 实施路线（T-009 / T-114 / ADR-015）

## Summary

M1 已关闭（除飞书联调）。本规划覆盖两阶段工作：

- **阶段 A（文档先行，用户明确要求）**：细致的需求拆分——新建 `docs/m2-requirements.md`（REQ-201~214，沿用 M1 拆分格式），tasks.md 落 M2 细分待办 T-201~214，changelog 留痕。
- **阶段 B（按拆分实施）**：按依赖顺序逐任务移植 llm_wiki `src/lib/` ingest 内核为 Python `app/compile/`，每任务完成即回归验证 + 三文档留痕。

LLM 接入已获用户确认：**OpenAI 兼容协议**（base_url + api_key + model），火山方舟/DeepSeek 等均可。

## Current State Analysis

**KnowSeq 侧已有**（可直接复用/对接）：
- [inbox.py](../../app/capture/inbox.py)：`write_material()` 素材模型，frontmatter 含 `compiled: false`（M2 消费标记，ADR-013）；素材在 `inbox/<source>/*.md`
- [config.py](../../app/config.py)：`get/set/save/secret/set_env`，`DEFAULTS` 深合并；`.env` 管敏感项（已有 `LLM_API_KEY` 占位）
- [server.py](../../app/web/server.py)：FastAPI 极简控制台（状态/素材/设置页），M2 在其上增编译 API
- 采集层并发风格：threading + stop_event（编译层保持同风格，不引入 asyncio）
- 依赖：Python 3.14 venv，requirements 已含 pyyaml/requests

**llm_wiki 侧**（`reference/llm_wiki/`，v0.6.11 已本地化，git 忽略）：
- 源码分析已完成（12 点报告，结论已固化到本规划 §设计决策）。移植素材齐备：ingest.ts（两步 CoT 编排）、ingest-queue/commit-coordinator/cache、dedup 系列、context-budget、sanitize、frontmatter、text-chunker、wiki-filename、lint 系列、review、enrich-wikilinks、llm-client/providers

**顶层需求**：FR-010（增量提炼/幂等/来源引用）、FR-011（自动+手动触发）、FR-040/042 M2 部分、NFR-002/004/005/006。

## 设计决策（需求拆分的全部关键决策，落 m2-requirements.md）

### D1 类型体系：五类条目替换 llm_wiki 九类（ADR-008 schema；2026-09-03 修订新增 query）

| 项 | 决策 |
|---|---|
| 类型 | `decision`（决策）/ `lesson`（教训）/ `concept`（概念）/ `connection`（连接）/ `query`（疑问，`status: open/resolved`） |
| 目录 | `knowledge/{decisions,lessons,concepts,connections,queries}/` + `knowledge/index.md` + `knowledge/log.md` |
| frontmatter | `type / title / created / updated / tags / related / sources`；`sources` 存 inbox 素材相对路径列表（实现 FR-010 来源引用 + NFR-005 溯源）；query 条目另有 `status: open/resolved` |
| 正文 | 自由 Markdown + `[[wikilink]]`（Obsidian 兼容） |
| 裁剪 | llm_wiki 的 `source/entity/comparison/synthesis/thesis/methodology/finding` 页型不引入（query 已于 2026-09-03 修订引入）；fallback source summary 改记入 `log.md`，不落条目页 |

### D2 LLM 接入：仅 OpenAI 兼容协议 + adapter 抽象（用户 2026-09-03 确认）

- REQ-202 只实现 OpenAI Chat Completions 兼容协议（llm_wiki `custom` provider 等价物）：`base_url`（自动补 `/chat/completions`）+ `Authorization: Bearer` + `model`；流式默认开（SSE）、非流式回退。覆盖火山方舟/DeepSeek/Kimi/智谱/通义兼容模式/Ollama/vLLM 等全部主流选项
- **provider adapter 抽象预留**：`llm_client.py` 以 `Provider` 协议（`build_request` / `parse_stream` / `parse_response` 三方法）组织（对齐 llm_wiki `getProviderConfig` 结构），日后新增 Anthropic Messages/Gemini 只增 adapter、不改调用方
- 裁剪：anthropic/google/azure/ollama 特化、claude-code/codex-cli 子进程 transport 全部不移植
- `ingest_reasoning` 与聊天 reasoning 分离、**默认 off**（thinking 模型结构化输出会静默丢页——llm_wiki 实测教训）
- `has_usable_llm` 守卫：未配 key/base_url → 编译状态 error 带提示，不影响采集

### D3 幂等与增量（FR-010 / NFR-004/006）

- **主幂等**：编译成功后回写 inbox frontmatter `compiled: true`（失败保持 false，重启自动重试）；队列按素材路径幂等入队
- **内容级缓存**：`compile_state/ingest-cache.json`（SHA256 + filesWritten 双条件命中——内容未变且产出文件仍在则跳过），用于"重新编译"防重复产出
- 条目文件名沿用 wiki-filename 规则：`{slug}-{YYYY-MM-DD}-{HHMMSS}.md`（slug 做 CJK/NFKC 处理）

### D4 并发模型（threading，与采集层一致）

- worker 并发 1~5（默认 1，可配 `compile.queue.concurrency`）；**准备并行、落盘 FIFO 串行**（commit coordinator → `queue.Queue` + 锁实现，失败/取消必须 release 防 FIFO 卡死）
- `MAX_RETRIES=3`；429/限流检测 → 暂停 15 分钟自动恢复；JSON 持久化队列状态机 `pending/processing/done/failed/cancelled`

### D5 预算与清洗（llm_wiki 三个关键提醒全采纳）

- 预算单位 = **字符非 token**，不引入 tokenizer：responseReserve 15% / index 5% / page 50%（单页上限 pageBudget×30%）；ingest max_tokens 按上下文阶梯
- sanitize 四步修复 + frontmatter 解析容错 + text-chunker（标题→段落→行→句→硬切，代码块/表格不拆）+ 长源分块分析（全局 digest + checkpoint 断点续跑）
- 输出语言：prompt 中文化撰写，`compile.output_language` 默认 `zh`

### D6 增强组件优先级（P1，核心跑通后再做）

| 组件 | 方案 | 触发 |
|---|---|---|
| lint | 结构化 lint 纯函数移植（孤儿/断链/无出链 + Levenshtein 建议 + stub 修复）；语义 lint 可选默认关 | 手动 + 队列排空后自动 |
| review | REVIEW 块解析 + `compile_state/review.json` + 控制台列表/手动处理；sweep/create-page/batch-research 裁剪 | ingest 产出时自动收集 |
| dedup | LLM 批扫路径（80 条/批 + overlap 8 + not-duplicates 白名单 + 串行合并队列）；embedding 预筛**仅留接口默认关** | 手动按钮 |
| enrich-wikilinks | LLM 补 related 链接 | 手动按钮 |

### D7 控制台集成（现有极简单页增强，React 化留 M4）

- API：`GET /api/compile/status`、`POST /api/compile/trigger`、`GET /api/compile/reviews`、`POST /api/compile/review/resolve`、`GET /api/knowledge`、dedup/lint/enrich 触发端点、设置页 compile 配置节
- 素材页加"编译状态"列与"立即编译"；状态页加编译区块（队列深度/LLM 可用性/最近产出）

### D8 裁剪清单（llm_wiki 有但不移植，均记录进 m2-requirements §0）

MinerU PDF、图片 captioning（PRD 明确多模态延后）、chat agent 与 chat-save-to-wiki、web-search/deep-research、wikilink-transform（渲染层，M4 再议）、tauri 依赖、zustand store（改显式状态/回调传参）。

## Proposed Changes

### 阶段 A：文档落地（先行，本规划批准后立即执行）

1. **新建 [docs/m2-requirements.md](../../docs/m2-requirements.md)**：§0 范围/裁剪/前置决策 + §1~§14（REQ-201~214，每 REQ 含描述/接口签名/移植来源/适配点/验收）+ §15 配置项枚举 + §16 整体验收 + §17 待办映射。REQ 与 T 一一对应：
   - REQ-201 工程基础：`app/compile/` 包骨架、config `compile:` 节、`.env` LLM 项、`knowledge/` 初始化 → T-201
   - REQ-202 LLM 客户端（OpenAI 兼容 stream_chat/超时/重试/守卫）→ T-202
   - REQ-203 文本处理套件（sanitize/frontmatter/chunker/slug/output-language）→ T-203
   - REQ-204 上下文预算（字符制）→ T-204
   - REQ-205 幂等体系（compiled 回写 + ingest-cache）→ T-205
   - REQ-206 持久化队列 + worker + commit coordinator → T-206
   - REQ-207 两步 CoT 编排 + 长源分块（中文 prompt、FILE/REVIEW 块协议、路径安全）→ T-207
   - REQ-208 落盘与知识库维护（write_blocks/page-merge/index/log 确定性更新）→ T-208
   - REQ-209 结构化 lint + 修复 → T-209
   - REQ-210 review 轻量闭环 → T-210
   - REQ-211 dedup（LLM 批扫）→ T-211
   - REQ-212 enrich-wikilinks → T-212
   - REQ-213 控制台 API + 页面集成 → T-213
   - REQ-214 端到端验收 + 文档同步 → T-214
2. **更新 [docs/tasks.md](../../docs/tasks.md)**：新增"M2 细分待办"表（T-201~214，覆盖 T-009/T-114）；"下一步"改为 M2 实施序
3. **更新 [docs/changelog.md](../../docs/changelog.md)**：M2 需求拆分条目

### 阶段 B：按 T-201→T-214 顺序实施（每任务：编码 → 回归验证 → 三文档留痕）

| 任务 | 关键产出（Python 模块，移植来源） | 验证方式 |
|---|---|---|
| T-201 | `app/compile/__init__.py`、config DEFAULTS 扩展、`knowledge/` 初始化 | 模块导入 + config 加载 + 目录生成 |
| T-202 | `app/compile/llm_client.py`（stream_chat，llm-client/custom provider 移植） | fake OpenAI 兼容服务（本地 http.server）测流式/非流式/超时/429 |
| T-203 | `app/compile/textproc.py` 或分文件（sanitize/frontmatter/chunker/slug，ingest-sanitize/frontmatter/text-chunker/wiki-filename 移植） | 移植 llm_wiki 对应 test fixtures 断言 |
| T-204 | `app/compile/context_budget.py` | 数值断言（15/5/50% 分配、阶梯） |
| T-205 | `app/compile/cache.py` + inbox `mark_compiled()`（ingest-cache 移植 + inbox 扩展） | 双条件命中/失效用例 |
| T-206 | `app/compile/queue.py`、`app/compile/coordinator.py`（ingest-queue/commit-coordinator 移植） | 持久化/重试/暂停恢复/FIFO 串行用例 |
| T-207 | `app/compile/ingest.py`（两步 CoT 编排 + 分块分析 + FILE/REVIEW 块解析，ingest.ts 骨架重写；Ported from 头注） | 伪造 LLM 响应走全流程单测 |
| T-208 | `app/compile/knowledge.py`（落盘/merge/index/log，ingest 写盘段 + page-merge 移植） | index/log 幂等更新用例 |
| T-209 | `app/compile/lint.py`（lint-structural-core 纯函数 + lint-fixes） | 移植断言：孤儿/断链/stub |
| T-210 | `app/compile/review.py`（REVIEW 块解析 + 存储，review-store 纯数据部分） | 解析/合并/稳定 id 用例 |
| T-211 | `app/compile/dedup.py`（detect/merge 批扫 + 白名单，dedup.ts/dedup-runner 退化路径） | fake LLM 合并用例 |
| T-212 | `app/compile/enrich.py`（enrich-wikilinks 移植） | 链接应用用例 |
| T-213 | `server.py` 扩展 + `static/` 页面增强 | TestClient API 冒烟 |
| T-214 | 端到端验收（真实素材 + 用户提供 API Key）+ 全文档同步 | 控制台手动触发 → knowledge/ 产出五类条目 → 重跑不重复 → Obsidian 可开 |

## Assumptions & Decisions

1. LLM 供应商 = OpenAI 兼容接口（用户 2026-09-03 确认）；Key 由用户在 `.env` 填写，T-214 实测时提供
2. threading 并发、不引 asyncio（与采集层一致，NFR-003 轻量）
3. 移植文件头部注明 `Ported from nashsu/llm_wiki (GPL-3.0)`（ADR-015 合规）；仅个人自用不分发
4. embedding 预筛默认关（无 embeddings 端点依赖），dedup 走 LLM 批扫退化路径（llm_wiki 同款）
5. 五类 schema（含 query，ADR-008 2026-09-03 修订）严格按 ADR-008，不引入 llm_wiki 其余页型
6. 编译管理器独立于采集 manager，由 run.py 启动，`compile.enabled/auto` 控制
7. 本轮不新增第三方依赖（httpx 可选——若 requests 不满足流式 SSE 则加 httpx，落地时定）

## Verification

- 每任务单测/脚本断言通过（移植 llm_wiki 对应 `__tests__` 的关键 fixtures）
- T-213 后 TestClient 冒烟：status/trigger/reviews/knowledge API 闭环
- T-214 端到端（真实 LLM）：inbox 放 2~3 条真实素材 → 自动/手动触发 → `knowledge/` 产出带 sources 引用的条目 → 重复执行幂等 → 长素材走分块路径 → lint/review/dedup 手动触发可用 → changelog/tasks/milestones 全部同步
