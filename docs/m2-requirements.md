# M2 编译层需求拆分（REQ-201 ~ REQ-214）

> 日期：2026-09-03　|　对应里程碑：M2　|　覆盖规划级任务：T-009 / T-114
> 依据：ADR-015（llm_wiki 移植）、ADR-008（编译层）、PRD FR-010/011/040-042、NFR-001~006
> 移植参考源码：`reference/llm_wiki/src/lib/`（v0.6.11，12 点源码分析结论已固化进本文件）

---

## §0 范围与前提

### 0.1 目标

将 inbox/ 素材经 OpenAI 兼容 LLM 提炼为 knowledge/ 五类知识条目：**inbox 素材 → LLM 两步 CoT → knowledge/{decisions,lessons,concepts,connections,queries}/ 条目 + index.md + log.md**，含幂等、队列、缓存、lint、review、dedup、enrich 全链路。

### 0.2 前置决策（已确认）

| # | 决策 |
|---|------|
| P1 | **仅实现 OpenAI Chat Completions 兼容协议**（火山方舟/DeepSeek/Kimi/智谱/通义/Ollama/vLLM 全覆盖），以 Provider adapter 抽象（build_request / parse_stream / parse_response 三方法）预留扩展，日后加协议只增不改 |
| P2 | 并发模型沿用采集层：**threading，不引 asyncio**；编译准备可并发、落盘 FIFO 串行 |
| P3 | 上下文预算**字符制**（不引 tokenizer），对齐 llm_wiki |
| P4 | 条目体系为 KnowSeq 五类（decision/lesson/concept/connection/query），替换 llm_wiki 九类；query 为 ADR-008 2026-09-03 修订新增（含 `status: open/resolved`）。内置中文 SCHEMA 常量，不读 schema.md 文件 |
| P5 | 敏感信息归属：base_url/model 写 config.yaml `compile.llm.*`；API Key 走 `.env`（`LLM_API_KEY`），与 M1 飞书凭据惯例一致 |
| P6 | lint 断链**自动建 type:query stub**（ADR-008 2026-09-03 修订引入 query 型后，恢复 llm_wiki 同款能力；文本修复能力保留） |

### 0.3 不在 M2 范围（裁剪清单）

- MinerU PDF 解析、图片 captioning（图片仅记占位描述）
- chat agent、web-search / deep-research
- wikilink-transform 渲染层转换（M4 渲染层再议）
- Anthropic Messages / Gemini / Azure / Bedrock 等其他协议（P1 已定）
- review 大件：sweep-reviews / review-create-page / review-batch-research（仅保留最小闭环）
- embedding 预筛（dedup 留接口默认关，直接 LLM 批扫）
- zustand / tauri / claude-code / codex-cli transport

### 0.4 合规（ADR-015）

所有移植文件头部注明 `Ported from nashsu/llm_wiki (GPL-3.0)`；仅个人自用不分发；reference/ 已 git 忽略。

---

## §1 REQ-201 包骨架与配置（T-201）

| 项 | 内容 |
|----|------|
| 描述 | 新建 `app/compile/` 包；config.yaml DEFAULTS 扩展 `compile` 节；knowledge/ 目录初始化 |
| 接口 | `app/compile/__init__.py` 导出 `CompileManager`；`app/compile/manager.py`：`CompileManager(config, inbox, llm=None)`，方法 `start()/stop()/trigger_all()/status()` |
| 移植来源 | 无直接对应（KnowSeq 自有，对齐 `app/capture/` 风格） |
| 适配点 | config `DEFAULTS` 增加 compile 全节（§15）；`paths.knowledge_dir=knowledge`；knowledge/ 下五类子目录（decisions/lessons/concepts/connections/queries）+ index.md + log.md 惰性初始化 |
| 验收 | import 无错；config.yaml 自动补全 compile 节；knowledge/ 结构生成 |

## §2 REQ-202 LLM 客户端（T-202）

| 项 | 内容 |
|----|------|
| 描述 | OpenAI 兼容流式客户端 + Provider adapter 抽象 |
| 接口 | `app/compile/llm_client.py`：<br>`class Provider(Protocol)`: `build_request(base_url, model, messages, overrides, stream) -> (url, headers, body)`、`parse_stream(line_iter) -> Iterator[str]`、`parse_response(resp) -> LlmResult`<br>`class OpenAICompatProvider`（实现三方法；baseURL 自动补 `/chat/completions`、Bearer 认证、`data:` SSE 行解析）<br>`stream_chat(config, messages, *, overrides=None, timeout=None) -> LlmResult{content, usage, stop_reason}`（唯一入口，requests `stream=True` + `iter_lines`）<br>`has_usable_llm(config) -> bool` 守卫<br>`@dataclass LlmResult(content, usage, stop_reason)` |
| 移植来源 | `reference/llm_wiki/src/lib/llm-client.ts`、`llm-provider-config.ts`（结构对齐） |
| 适配点 | fetch SSE → requests SSE；`ingest_reasoning`（默认 false）与聊天 reasoning 分离传参，防 thinking 模型结构化输出静默丢页；429 暂停信号上抛给队列 |
| 验收 | Mock HTTP 服务流式返回可解析；base_url 末尾带/不带 `/v1` 均可；无 Key 时 `has_usable_llm` 返回 False 且 trigger 安全跳过 |

## §3 REQ-203 文本处理（T-203）

| 项 | 内容 |
|----|------|
| 描述 | sanitize 四步修复、文件名生成，两个纯函数模块 |
| 接口 | `app/compile/sanitize.py`：`sanitize_document(text) -> str`（剥外层代码栅栏 / 剥 `frontmatter:` 前缀 / 补开头 `---` / 修复 frontmatter 内 wikilink 列表）<br>`app/compile/filename.py`：`make_entry_filename(title, now=None) -> str`（NFKC + Unicode 字母数字连字符 slug + 50 截断 + `{slug}-{YYYY-MM-DD}-{HHMMSS}.md`） |
| 移植来源 | `ingest-sanitize.ts`、`wiki-filename.ts` |
| 适配点 | 纯函数直接移植，仅改语言与命名。**裁剪：`text-chunker.ts` 系 llm_wiki 死代码（无调用方），不移植；长源语义分块（ingest.ts 内 `splitSourceIntoSemanticChunks`）归 REQ-208/T-208 实现** |
| 验收 | 移植 llm_wiki `__tests__` 对应 fixtures 全部通过 |

## §4 REQ-204 上下文预算（T-204）

| 项 | 内容 |
|----|------|
| 描述 | 字符制预算计算 |
| 接口 | `app/compile/context_budget.py`：`compute_budget(max_context) -> Budget{index_budget, page_budget, response_reserve, max_single_page}`；常量 `RESPONSE_RESERVE=0.15 / INDEX_BUDGET=0.05 / PAGE_BUDGET=0.50`；单页上限 = page_budget×30%（下限 5000 字符） |
| 移植来源 | `context-budget.ts` |
| 适配点 | 纯函数直接移植；**单位是字符不是 token** |
| 验收 | 边界值单测（max_context 极小/极大时单页下限 5000 生效） |

## §5 REQ-205 幂等与缓存（T-205）

| 项 | 内容 |
|----|------|
| 描述 | compiled 回写主幂等 + 内容缓存双条件命中 |
| 接口 | inbox 侧：复用 `Inbox.write_material` 既有 `compiled: false` frontmatter，编译成功后 `mark_compiled(path)` 回写 `compiled: true` + `compiled_at`<br>`app/compile/cache.py`：`IngestCache(base_dir)`，`get(content_hash) -> Optional[CacheEntry]`、`put(entry)`；`@dataclass CacheEntry{hash, timestamp, files_written}`；**双条件命中**：SHA256 相同 且 files_written 全部仍存在 |
| 移植来源 | `ingest-cache.ts`；compiled 标记为 KnowSeq 自有（llm_wiki 无，改为状态推进防重） |
| 适配点 | 缓存持久化 `.knowseq/compile-cache.json`（原 `.llm-wiki/ingest-cache.json`） |
| 验收 | 同一素材二次编译直接命中缓存不调 LLM；删除产物文件后缓存失效重编 |

## §6 REQ-206 编译队列与落盘协调（T-206）

| 项 | 内容 |
|----|------|
| 描述 | 持久化任务队列 + 落盘 FIFO 串行协调 |
| 接口 | `app/compile/queue.py`：`CompileQueue(base_dir)`，`upsert(task) / take() / complete(id) / fail(id, err) / pause(seconds) / snapshot()`；`@dataclass CompileTask{id, source_path, status: pending/processing/done/failed/cancelled, retry_count}`；持久化 `.knowseq/compile-queue.json`<br>`app/compile/commit.py`：`CommitCoordinator`，`reserve() -> 上下文管理器`（threading.Lock + Condition 实现_FIFO；失败/取消必须 release 防卡死） |
| 移植来源 | `ingest-queue.ts`（MAX_RETRIES=3、429 → 暂停 15min 自动恢复、epoch 防陈旧 worker）、`ingest-commit-coordinator.ts` |
| 适配点 | Promise 链 → threading.Condition；worker 数 1-5 默认 1（`compile.queue.concurrency`） |
| 验收 | kill 进程后重启队列状态恢复；模拟 LLM 失败 3 次后任务 failed；429 触发全局暂停并自动恢复；并发 reserve 严格串行 |

## §7 REQ-207 两步 CoT 提炼编排（T-207）

| 项 | 内容 |
|----|------|
| 描述 | 编译核心：单素材 → 两步 CoT → FILE/REVIEW 块解析 |
| 接口 | `app/compile/pipeline.py`：`compile_one(task, ctx) -> CompileOutcome{files, reviews, ok, err}`，九步流程：<br>1 读素材（>预算上限则走长源分块）→ 2 Step1 Analysis（temperature 0.1 / max_tokens 4096）→ 3 Step2 Generation（携带 Analysis 产出）→ 4 解析 FILE 块（regex `---FILE: <path>---` … `---END FILE---`）→ 5 截断块修复（LLM 重试一次）→ 6 解析 REVIEW 块（type ∈ contradiction/duplicate/missing-page/suggestion）→ 7 路径安全检查 `is_safe_path(rel)`（只允许 knowledge/ 下相对路径）→ 8 sanitize → 9 交 CommitCoordinator 落盘<br>`app/compile/schema.py`：内置中文 SCHEMA 常量（五类定义，query 另有 status: open/resolved；frontmatter 规范 type/title/created/updated/tags/related/sources）<br>`app/compile/blocks.py`：`parse_file_blocks(text) / parse_review_blocks(text)` |
| 移植来源 | `ingest.ts`（autoIngestImpl 步骤序列为骨架重写，不强搬 1300+ 行）、`ingest-parse` fixtures |
| 适配点 | 九类 → 五类 SCHEMA；schema/purpose 改内置常量；fallback：LLM 产出无法解析时摘要记 log.md 不落条目页 |
| 验收 | 用 fixtures 喂 Step2 产出文本，FILE/REVIEW 解析正确；非法路径被拒 |

## §8 REQ-208 长源分块与落盘维护（T-208）

| 项 | 内容 |
|----|------|
| 描述 | 超长素材分块递归编译 + knowledge/ index.md 与 log.md 维护 |
| 接口 | `app/compile/long_source.py`：`analyze_long_source(chunks, ctx, *, checkpoint_key) -> CompileOutcome`（target = budget×0.55，overlap 800-3000 字符自适应，checkpoint 断点续跑）<br>`app/compile/indexer.py`：`update_index(knowledge_dir, entries)`（按五类分区+标题索引）、`append_log(knowledge_dir, line)` |
| 移植来源 | `ingest.ts`（analyzeLongSourceInChunks + splitSourceIntoSemanticChunks）、index/log 维护 |
| 适配点 | checkpoint 持久化 `.knowseq/compile-checkpoints/` |
| 验收 | 构造超长素材（>50k 字符）分块编译产出完整；中断重启后从 checkpoint 续跑；index.md 覆盖全部条目 |

## §9 REQ-209 结构化 lint（T-209）

| 项 | 内容 |
|----|------|
| 描述 | knowledge/ 全库结构化 lint：断链/同名/重复候选 |
| 接口 | `app/compile/lint.py`：`lint_knowledge(knowledge_dir) -> list[LintIssue{kind, file, detail, suggestion}]`；纯函数核心 `suggest_link_targets(broken, titles)`（相似度阈值 0.74、CJK 单字权重 0.35、同名 0.96、包含 0.82、候选上限 64）；文本修复 `append_wikilink(file, link)` / `rewrite_wikilink_target(file, old, new)`；断链无合适建议时 `create_stub(knowledge_dir, slug)` 自动建 type:query stub 条目（status: open，llm_wiki 同款）；`lint.semantic=false` 时语义相似关闭 |
| 移植来源 | `lint-structural-core.ts`（纯函数）、`lint-fixes.ts` |
| 适配点 | **断链自动建 type:query stub**（P6 决策，ADR-008 2026-09-03 修订引入 query 型后恢复 llm_wiki 能力） |
| 验收 | fixtures：断链建议、同名检测、CJK 权重行为与 llm_wiki 一致 |

## §10 REQ-210 review 轻量闭环（T-210）

| 项 | 内容 |
|----|------|
| 描述 | REVIEW 块解析 → 持久化 → 控制台可见 → 可标记解决 |
| 接口 | `app/compile/review_store.py`：`ReviewStore(base_dir)`，`add(items) / list(status=None) / resolve(id, note=None)`；`@dataclass ReviewItem{id, type, title, detail, status: open/resolved, created, source_path}`；`review_id_for(item) = f"{type}::{normalize_title(title)}"`（内容派生稳定 id） |
| 移植来源 | `review-store.ts`（注意原文件在 `src/stores/` 非 lib/）、`ingest.ts` 的 parseReviewBlocks 段 |
| 适配点 | 持久化 `.knowseq/reviews.json`；大件裁剪（§0.3） |
| 验收 | 同一 REVIEW 重复出现不产生重复 id；resolve 后不再出现在 open 列表 |

## §11 REQ-211 dedup LLM 批扫（T-211）

| 项 | 内容 |
|----|------|
| 描述 | 五类条目重复检测与合并 |
| 接口 | `app/compile/dedup.py`：`extract_entity_summary(knowledge_dir) -> list[dict]`（纯数据）→ `detect_duplicate_groups(summaries, ctx) -> list[dict]`（LLM 批扫输出 JSON groups）→ `merge_duplicate_group(group, ctx) -> MergeResult`；`DEDUP_PREFILTER_THRESHOLD=0.68`、80 条/批 + overlap 8；≤250 页全扫，>250 页无预筛直接返回空（防挂起）；not-duplicates 白名单持久化；串行单 worker |
| 移植来源 | dedup 系列（`dedup-*.ts`） |
| 适配点 | embedding 预筛接口预留默认关；九类 → 五类 |
| 验收 | 构造两条近似条目可检出并合并为一条且 related/sources 保留 |

## §12 REQ-212 enrich-wikilinks（T-212）

| 项 | 内容 |
|----|------|
| 描述 | 为条目正文补充相关条目 wikilink |
| 接口 | `app/compile/enrich.py`：`enrich_wikilinks(knowledge_dir, ctx, *, dry_run=False) -> EnrichResult`（手动触发，遍历条目 → LLM 建议 related → 校验目标存在 → 写入 frontmatter related 与正文链接） |
| 移植来源 | llm_wiki enrich 相关模块 |
| 适配点 | 手动触发（不做后台自动） |
| 验收 | dry_run 只报告不改文件；真实运行后 related 字段与正文链接一致且目标均存在 |

## §13 REQ-213 控制台集成（T-213）

| 项 | 内容 |
|----|------|
| 描述 | 编译 API + 页面增强 |
| 接口 | server 新增路由：<br>`GET  /api/compile/status`（队列快照 + has_usable_llm + 最近编译）<br>`POST /api/compile/trigger`（body: `{scope: "all"|"path", path?}`）<br>`GET  /api/compile/reviews`、`POST /api/compile/reviews/resolve`（body: `{id, note?}`）<br>`GET  /api/knowledge`（五类条目列表 + 条目内容）<br>`POST /api/compile/dedup`、`POST /api/compile/lint`、`POST /api/compile/enrich` |
| 移植来源 | 无（KnowSeq 自有，对齐 M1 采集 API 风格） |
| 适配点 | 前端控制台新增"编译"页：状态卡片、触发按钮、review 列表与解决操作、knowledge 浏览 |
| 验收 | curl 全部端点可用；页面可看状态/触发/解决 review |

## §14 REQ-214 端到端验收（T-214）

| 项 | 内容 |
|----|------|
| 描述 | 真实 LLM 全链路验收 + 文档同步 |
| 内容 | ① 用户提供 base_url/model/Key → ② 拖真实素材入 inbox → ③ 自动编译产出五类条目 + index/log → ④ 二次编译命中缓存 → ⑤ review/dedup/lint/enrich 全走通 → ⑥ 控制台全流程 → ⑦ changelog/milestones/tasks 同步 |
| 验收 | 全链路无人工修文件即闭环；幂等/断点/暂停恢复行为符合 §5/§6/§8 |

---

## §15 配置项枚举

### config.yaml（新增 compile 节）

```yaml
compile:
  enabled: true            # 总开关
  auto: true               # inbox 变化自动入队（轮询）
  poll_interval: 30        # 秒
  llm:
    base_url: ""           # 如 https://ark.cn-beijing.volces.com/api/v3
    model: ""
    temperature: 0.7       # Step2 生成温度；Step1 固定 0.1
    max_context: 204800    # 字符制预算基准
    streaming: true
    request_timeout_min: 30
    ingest_reasoning: false  # thinking 关闭，防结构化输出丢页
  output_language: zh
  queue:
    concurrency: 1         # 1-5
    max_retries: 3
  lint:
    semantic: false
  dedup:
    threshold: 0.68
```

### .env（仅一项）

- `LLM_API_KEY` —— 编译层 API Key（敏感，不落 config.yaml、不落日志）

## §16 NFR（M2 段）

| # | 要求 |
|---|------|
| NFR-201 | API Key 不落任何日志/控制台输出 |
| NFR-202 | 零新第三方依赖：requests `stream=True` + `iter_lines` 解析 SSE；如实测不满足再议 httpx（需 changelog 记录） |
| NFR-203 | 增量可恢复：队列/checkpoint/缓存持久化，进程重启不丢进度 |
| NFR-204 | 落盘串行（FIFO），任何路径下 coordinator 必须 release（try/finally） |

## §17 待办映射

| REQ | 任务 | 说明 |
|-----|------|------|
| 201 | T-201 | 包骨架 + config + knowledge 初始化 |
| 202 | T-202 | LLM 客户端 |
| 203 | T-203 | sanitize / filename（chunker 裁剪，见 §3） |
| 204 | T-204 | 上下文预算 |
| 205 | T-205 | compiled 标记 + 缓存 |
| 206 | T-206 | 队列 + commit coordinator |
| 207 | T-207 | 两步 CoT 编排 + 块解析 + SCHEMA |
| 208 | T-208 | 长源分块 + index/log |
| 209 | T-209 | lint |
| 210 | T-210 | review 轻量闭环 |
| 211 | T-211 | dedup 批扫 |
| 212 | T-212 | enrich-wikilinks |
| 213 | T-213 | 控制台集成 |
| 214 | T-214 | 端到端验收（需用户提供 LLM 凭据） |
