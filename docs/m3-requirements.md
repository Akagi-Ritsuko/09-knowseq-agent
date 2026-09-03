# M3 大脑层需求拆分（REQ-301 ~ REQ-306）

> 日期：2026-09-03　|　对应里程碑：M3　|　覆盖规划级任务：T-010
> 依据：ADR-009（LightRAG 大脑层）、PRD FR-020/021/022、architecture.md §2.3
> 上游依赖：M2 编译层（REQ-201~214）已关闭——knowledge/ 五类条目由编译层产出

---

## §0 范围与前置决策

### 0.1 目标

对 `knowledge/`（五类 Markdown 条目）构建 LightRAG 大脑：**向量索引 + 自动知识图谱 + 引用溯源**，通过同步门面暴露给 Web 层（检索 / 问答 / 图谱导出 / 状态）。

### 0.2 前置决策（本里程碑固化）

| # | 决策 |
|---|------|
| D1 | **asyncio 内部化**：LightRAG 是 asyncio 库（ainsert/aquery）。M2 决策 P2"threading 不引 asyncio"约束采集/编译层；M3 在 `app/brain/` 内使用**专用后台事件循环线程**（独立 loop + `run_coroutine_threadsafe`）封装，对外提供**同步**接口（engine.index / search / ask / graph），不改变采集/编译层风格 |
| D2 | **依赖 lightrag-hku**（ADR-009 预期）：新增第三方依赖（唯一例外，其余模块仍零新依赖）；存储用**默认本地**（JsonKVStorage + NanoVectorDB + NetworkX），不引 PostgreSQL/Neo4j/Redis 等外部服务 |
| D3 | **embedding/LLM 走 OpenAI 兼容**：embedding 用 `lightrag.llm.openai.openai_embed`（base_url 指向火山方舟等兼容端点）；问答 LLM 复用 `compile.llm` 配置（base_url/model/Key 同源），可在 `brain.llm` 单独覆盖 |
| D4 | **索引增量幂等**：以文件相对路径为 doc_id + 内容哈希做增量（LightRAG doc_status 记录）；内容未变的条目不重复触发建图，避免重复 token 开销 |
| D5 | **图谱导出格式**：networkx 图 → `{nodes, edges}` JSON（vis-network 兼容：`{id, label, type}` / `{source, target, relation}`），供 M4 前端（T-115）直接可视化 |
| D6 | Key 归属沿用 NFR-002：`LLM_API_KEY` 复用（brain 不新增敏感项）；embedding/LLM base_url/model 写 config.yaml `brain.*` |

### 0.3 不在 M3 范围（裁剪）

- 交互层图谱可视化页面、问答聊天 UI、知识管理页（属 M4 / T-115，M3 仅控制台简易面板 + API）
- LightRAG Server / WebUI / Docker / RAG-Anything 多模态、reranker、RAGAS 评估、OpenSearch/PostgreSQL/Neo4j 等高级存储
- 多模态文档解析（PDF/Office）、chat agent、deep-research
- 图谱编辑/手动增删实体

### 0.4 与现有约定对齐

- 并发：brain 内部 asyncio 但对外同步；FastAPI 端点仍为同步 def（FastAPI 放线程池执行，安全）
- 异常：LLM/embedding 未配置时端点返回 400 提示（对齐 T-213 `_require_compile` 风格）；Key 不落日志
- 运行时目录：LightRAG working_dir = `{knowledge_dir.parent}/.knowseq/brain`（与 cache/queue/reviews 同级）

---

## §1 REQ-301 大脑引擎封装（T-301）

| 项 | 内容 |
|----|------|
| 描述 | 依赖落地 + config `brain:` 节 + `app/brain/engine.py` 同步门面 |
| 接口 | `LightRAGEngine(config)`：`start()/stop()/is_ready()`；内部懒初始化专用事件循环线程，`_run(coro)` 用 `run_coroutine_threadsafe` 提交并同步等待；`llm_func/embedding_func` 由 config 构建（OpenAI 兼容，复用 `compile.llm.base_url/model` 与 `.env LLM_API_KEY`） |
| 适配点 | LightRAG 1.5.x asyncio API（`await rag.ainsert/...`）包装为同步；embedding 维度由 `openai_embed` 返回推断或 config `brain.embedding.dim` 显式指定 |
| 验收 | 模块导入 + 引擎实例化不触发网络请求；`is_ready()` 反映配置完备性；`start/stop` 干净（线程退出、无泄漏） |

## §2 REQ-302 知识库索引（T-302）

| 项 | 内容 |
|----|------|
| 描述 | 对 knowledge/ 五类条目建立/更新 LightRAG 索引（增量幂等） |
| 接口 | `brain.index(knowledge_dir) -> BrainIndexResult{inserted, skipped, elapsed}`；扫描五类 `*.md` → 按 rel 路径 + 内容哈希对比（复用 compile.cache sha256_text）→ 新增/变更条目 `ainsert(text, file_path=rel)` |
| 适配点 | doc_id 用 rel 路径；正文 = frontmatter + 正文全文（LightRAG 自抽实体建图）；空库不报错返回全 0 |
| 验收 | 首次索引后条目可被语义检索命中；二次索引（内容未变）inserted=0（幂等）；某条内容修改后二次索引只重插该条 |

## §3 REQ-303 语义检索（T-303）

| 项 | 内容 |
|----|------|
| 描述 | 无生成式回答的向量语义检索（FR-020） |
| 接口 | `brain.search(query, top_k=10) -> list[SearchHit{content, file_path, score}]`（LightRAG naive/mix 检索返回 contexts） |
| 适配点 | 抽取 LightRAG 返回片段并归一化 file_path 为 knowledge/ 相对路径 |
| 验收 | 查询与某条目语义相关时命中该条目；返回内容可回溯到具体文件；空库返回空列表 |

## §4 REQ-304 带引用问答（T-304）

| 项 | 内容 |
|----|------|
| 描述 | 基于知识库的问答 + 引用溯源（FR-022） |
| 接口 | `brain.ask(query, mode="hybrid") -> AskResult{answer, contexts:[{content, file_path}]}`；mode ∈ local/global/hybrid/naive/mix |
| 适配点 | LightRAG `aquery(query, param=QueryParam(mode=...))` 返回 answer + 上下文；sources 映射回条目文件路径；答案语言跟随 `compile.output_language`（zh） |
| 验收 | 回答内容基于知识库（非编造）；contexts 含来源文件；mode 参数可切换 |

## §5 REQ-305 图谱导出（T-305）

| 项 | 内容 |
|----|------|
| 描述 | 导出 LightRAG 自动抽取的知识图谱（FR-021） |
| 接口 | `brain.graph() -> GraphData{nodes:[{id,label,type}], edges:[{source,target,relation}]}`（networkx 图 → vis-network 兼容 JSON） |
| 适配点 | LightRAG 1.5.x 图接口（`get_graph()`）异步封装；节点附 entity type，边附 relation；空图返回空节点/边 |
| 验收 | 索引后节点/边非空；JSON 结构被前端可消费；空库返回空数组不报错 |

## §6 REQ-306 大脑 API 与控制台面板（T-306）

| 项 | 内容 |
|----|------|
| 描述 | server 暴露 brain API + 控制台简易"大脑"面板 |
| 接口 | `GET /api/brain/status`（enabled/ready/索引统计）<br>`POST /api/brain/index`（body `{rebuild: bool}`，增量或全量重建）<br>`POST /api/brain/query`（body `{query, mode?, top_k?}`）<br>`GET /api/brain/search?q=&top_k=`<br>`GET /api/brain/graph` |
| 适配点 | 对齐 T-213 编译 API 风格（`_require_brain` 404 兜底、LLM 未配 400）；前端静态页加"大脑"卡片：状态/重建/问答输入/图谱 JSON 预览 |
| 验收 | curl 全部端点可用；控制台可看状态、重建索引、问答返回带引用、图谱可预览 |

---

## §7 配置项枚举（config.yaml 新增 brain 节）

```yaml
brain:
  enabled: true          # 总开关
  # embedding（OpenAI 兼容；Key 复用 .env LLM_API_KEY）
  embedding:
    base_url: ""         # 如 https://ark.cn-beijing.volces.com/api/v3
    model: ""            # 如 doubao-embedding-large
    dim: 0               # 0=运行时由返回维度推断
  # 问答 LLM（缺省复用 compile.llm 的 base_url/model）
  llm:
    base_url: ""         # 空=复用 compile.llm.base_url
    model: ""
```

## §8 整体验收（对应 FR-020/021/022 与里程碑 M3 验收）

- **语义检索**：对已建索引的知识库，`search` 能命中语义相关条目，来源可回溯
- **图谱导出**：`graph()` 返回节点/边非空、格式可消费
- **带引用问答**：`ask` 回答基于知识库且 contexts 含来源文件
- **增量幂等**：二次索引不重复插入；条目变更只重插该条
- **控制台**：brain API 全端点可用、面板可操作
- 文档同步：changelog/tasks/milestones 留痕，T-010 done

## §9 待办映射

| REQ | 任务 | 覆盖规划级 |
|---|---|---|
| REQ-301 | T-301 | T-010 |
| REQ-302 | T-302 | T-010 |
| REQ-303/304 | T-303 | T-010 |
| REQ-305 | T-304 | T-010 |
| REQ-306 | T-305 | T-010 |
| §8 验收 | T-306 | T-010 |
