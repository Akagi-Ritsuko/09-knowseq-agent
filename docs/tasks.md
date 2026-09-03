# 任务进度追踪（docs/tasks.md）

> 当前状态第一入口。每次改动请同步更新本文档（见 ai-collab.md §2）。
> 状态：todo / doing / done。编号 T-三位数，递增不复用。

## 当前任务

| ID | 描述 | 关联 | 状态 | 完成日期 |
|---|---|---|---|---|
| T-001 | 落地项目文档体系（README/ai-collab/prd/architecture/milestones/tasks/changelog/ADR×11） | M0 | done | 2026-09-02 |
| T-002 | M1-采集层：会议音频采集（VibeVoice-ASR-BitNet 本地转写）接入 | M1 / ADR-014 | done | 2026-09-02 |
| T-003 | M1-采集层：剪贴板监控（微信/企微） | M1 / ADR-004 | done | 2026-09-02 |
| T-004 | M1-采集层：飞书机器人事件 + 云文档导入 | M1 / ADR-005 | doing | |
| T-005 | M1-采集层：watchdog 文件监听 + 拖拽/批量导入 | M1 / ADR-006 | done | 2026-09-02 |
| T-006 | M1-采集层：网页 URL 抓取正文 | M1 / ADR-007 | done | 2026-09-02 |
| T-007 | M1-采集层：手动导入（粘贴文本/拖入文件） | M1 | done | 2026-09-02 |
| T-008 | M1-采集层：托盘图标左键开关采集雏形 | M1 / ADR-011 | done | 2026-09-02 |
| T-009 | M2-编译层：云端 LLM 提炼流水线（inbox→知识条目，移植 llm_wiki ingest 内核） | M2 / ADR-008 / ADR-015 | done | 2026-09-03 |
| T-010 | M3-大脑层：LightRAG 接入（向量+图谱+引用溯源） | M3 / ADR-009 | done | 2026-09-03 |
| T-011 | M4-交互层：FastAPI + React 前端（问答/图谱/控制/管理/设置，移植 llm_wiki 组件） | M4 / ADR-010 / ADR-015 | doing | |
| T-012 | M5-Windows 集成完善 + 演示打磨 | M5 / ADR-011 | todo | |

## M1 细分待办（实施顺序）

> 详细需求见 [m1-requirements.md](m1-requirements.md)（REQ-101~111）。规划级任务 T-002~T-008 由下列细分任务覆盖。

| ID | 描述 | 关联 REQ | 关联 ADR | 覆盖规划级 | 状态 |
|---|---|---|---|---|---|
| T-101 | 工程基础：venv(py -3)/依赖/目录骨架/config.yaml+.env/config.py | REQ-101 | — | T-002~008 前置 | done |
| T-102 | inbox 写入服务与素材模型（write_material/去重/frontmatter） | REQ-102 | ADR-013 | T-002~008 前置 | done |
| T-103 | 采集管理器：各源启停/状态聚合 | REQ-103 | — | T-002~008 前置 | done |
| T-104 | VibeVoice-ASR-BitNet 转写源接入（asr_infer 子进程：音频文件→结构化转写→inbox/meeting） | REQ-104 | ADR-014 | T-002 | done |
| T-105 | 剪贴板监控（Windows 轮询+去重+截断） | REQ-105 | ADR-004 | T-003 | done |
| T-106 | 飞书机器人事件（WebSocket 长连接）+ 云文档导入 | REQ-106 | ADR-005 | T-004 | doing |
| T-107 | watchdog 文件监听 + 热文件夹（拖拽/批量） | REQ-107 | ADR-006 | T-005 | done |
| T-108 | 网页抓取（URL→readability 正文→inbox/web） | REQ-108 | ADR-007 | T-006 | done |
| T-109 | 手动导入（控制台粘贴文本/上传文件） | REQ-109 | — | T-007 | done |
| T-110 | 极简控制台（FastAPI + 状态/开关/导入/素材/设置页） | REQ-110 | ADR-012 | T-008 前置 | done |
| T-111 | 托盘雏形（pystray 左键开关 + 右键菜单） | REQ-111 | ADR-011 | T-008 | done |
| T-112 | M1 端到端验收 + 文档同步（changelog/tasks/milestones） | §13 | — | M1 收尾 | done |

> **M1 验收完成（2026-09-02，T-112 收尾）**：真实桌面验收全部通过——T-104 meeting 转写（asr_infer.exe + VibeVoice-ASR-BitNet gguf，drop 热文件夹 → `inbox/meeting/` 产出转写稿）；T-105 剪贴板自动入库；T-110 控制台各页面（状态/素材/设置含"会议音频 (VibeVoice-ASR)"开关）；T-111 托盘左键开关采集；T-109 粘贴导入。**M1 唯一遗留：T-106 飞书联调**（凭据就绪后补做，REQ-106 验收前提），T-004 保持 doing。T-113（说话人/时间戳字段）待转写输出 schema 确认后处置。

> **运行期崩溃修复（2026-09-02）**：真实桌面首次运行即崩，faulthandler 定位 `read_clipboard_text` Access Violation：Win32 调用未声明 argtypes/restype，64 位下句柄按 32 位截断成非法指针。改为显式原型 + `wstring_at`，沙盒实测读取成功；`run.py` 加 faulthandler 与异常兜底（窗口不再闪退）。此前的"沙盒限制"结论系误判，实为同一 bug。

> **代码审查修复（2026-09-02）**：对 app/ 做通用代码审查，9 个问题全部修复并回归验证通过（飞书 SDK 用法、inbox 加锁与 meta YAML 转义、采集线程 stop_event、文件稳定检测、网页编码回退、config deepcopy、剪贴板基线、控制台 Host/Origin 校验），详见 changelog.md。各任务状态不变，仍以真实环境验收为准。

## M2 细分待办（实施顺序）

> 详细需求见 [m2-requirements.md](m2-requirements.md)（REQ-201~214）。规划级任务 T-009/T-114 由下列细分任务覆盖。前置决策：仅 OpenAI 兼容协议 + Provider adapter 抽象；threading 并发；字符制预算；五类条目 schema（ADR-008 2026-09-03 修订新增 query）。

| ID | 描述 | 关联 REQ | 移植来源（llm_wiki） | 覆盖规划级 | 状态 |
|---|---|---|---|---|---|
| T-201 | 包骨架：`app/compile/` + config compile 节 + knowledge/ 五类目录（含 queries/）与 index/log 初始化 | REQ-201 | — | T-009 前置 | done |
| T-202 | LLM 客户端：OpenAI 兼容流式（requests SSE）+ Provider adapter（build_request/parse_stream/parse_response）+ has_usable_llm | REQ-202 | llm-client.ts / llm-provider-config.ts | T-009/T-114 | done |
| T-203 | 文本处理纯函数：sanitize 四步修复 / filename slug（text-chunker 为源码死代码，裁剪不移植） | REQ-203 | ingest-sanitize / wiki-filename | T-114 | done |
| T-204 | 上下文预算（字符制：15%/5%/50%，单页上限下限 5000） | REQ-204 | context-budget.ts | T-114 | done |
| T-205 | 幂等：inbox `compiled: true` 回写 + 缓存双条件命中（SHA256 + files_written 存在） | REQ-205 | ingest-cache.ts + 自有 | T-114 | done |
| T-206 | 编译队列（持久化/MAX_RETRIES=3/429 暂停 15min）+ 落盘 FIFO CommitCoordinator | REQ-206 | ingest-queue / ingest-commit-coordinator | T-114 | done |
| T-207 | 提炼核心：两步 CoT（Step1 temp 0.1→Step2）+ FILE/REVIEW 块解析 + 路径安全 + 五类中文 SCHEMA 常量 | REQ-207 | ingest.ts（autoIngestImpl 骨架重写） | T-114 | done |
| T-208 | 长源分块（target=budget×0.55、checkpoint 续跑）+ knowledge/ index.md 与 log.md 维护 | REQ-208 | ingest.ts（analyzeLongSourceInChunks + splitSourceIntoSemanticChunks） | T-114 | done |
| T-209 | 结构化 lint（断链 0.74/CJK 0.35/同名 0.96/包含 0.82；断链自动建 type:query stub + 文本修复） | REQ-209 | lint-structural-core / lint-fixes | T-114 | done |
| T-210 | review 轻量闭环：解析→持久化→列表→解决（内容派生稳定 id） | REQ-210 | review-store.ts | T-114 | done |
| T-211 | dedup LLM 批扫（阈值 0.68、80 条/批、≤250 全扫、not-duplicates 白名单；embedding 预筛默认关） | REQ-211 | dedup-*.ts | T-114 | done |
| T-212 | enrich-wikilinks（手动触发，related 校验目标存在） | REQ-212 | enrich 相关模块 | T-114 | done | 2026-09-03 |
| T-213 | 控制台集成：compile API 8 端点 + 编译页（状态/触发/review/knowledge 浏览） | REQ-213 | — | T-009 | done | 2026-09-03 |
| T-214 | 端到端验收 + 文档同步（需用户提供 base_url/model/Key） | REQ-214 | — | M2 收尾 | done | 2026-09-03 |

## M3 细分待办（实施顺序）

> 详细需求见 [m3-requirements.md](m3-requirements.md)（REQ-301~306）。规划级任务 T-010 由下列细分任务覆盖。前置决策：LightRAG（lightrag-hku）asyncio 内部化、对外同步门面（D1）；默认本地存储（JsonKV+NanoVectorDB+NetworkX）；embedding/LLM 走 OpenAI 兼容（D3）；索引增量幂等（D4）。

| ID | 描述 | 关联 REQ | 覆盖规划级 | 状态 |
|---|---|---|---|---|
| T-301 | 大脑引擎封装：安装 lightrag-hku、config `brain:` 节、`app/brain/engine.py` 同步门面（后台事件循环线程 + run_coroutine_threadsafe） | REQ-301 | T-010 | done | 2026-09-03 |
| T-302 | 知识库索引：扫描五类条目 → 增量 ainsert（rel 路径 doc_id + 内容哈希幂等） | REQ-302 | T-010 | done | 2026-09-03 |
| T-303 | 语义检索 + 带引用问答：search/ask（mode 切换、contexts 来源映射） | REQ-303/304 | T-010 | done | 2026-09-03 |
| T-304 | 图谱导出：networkx → nodes/edges JSON（vis-network 兼容） | REQ-305 | T-010 | done | 2026-09-03 |
| T-305 | brain API 5 端点 + 控制台"大脑"面板 | REQ-306 | T-010 | done | 2026-09-03 |
| T-306 | M3 端到端验收（真实 embedding/LLM 语义检索/图谱/问答）+ 文档同步 | §8 | T-010 | done | 2026-09-03 |

## M4 细分待办（实施顺序）

> 详细需求见 [m4-requirements.md](m4-requirements.md)（REQ-401~411）。规划级任务 T-011/T-115 由下列细分任务覆盖。前置决策：React 19 + Vite + TS（D1）；webui/ 源码 + dist 静态托管、验收后旧 static 下线（D2）；图谱 sigma.js v3 + graphology + ForceAtlas2 + Louvain（D3）；taste-skill 设计系统先行（D4）；后端仅补齐管理 API 无破坏性变更（D6）。

| ID | 描述 | 关联 REQ | 关联 ADR | 覆盖规划级 | 状态 |
|---|---|---|---|---|---|
| T-401 | 前端工程骨架：webui/（Vite+React19+TS）、dev 代理 /api、构建输出 app/web/dist、FastAPI dist 优先/static 兜底、七页路由骨架 | REQ-401 | ADR-010/015 | T-011/T-115 前置 | done（2026-09-03） |
| T-402 | 设计系统：taste-skill（design-taste-frontend v2）调研→dial（中密度/克制动效）→tokens+基础组件，全站共享 | REQ-402 | — | T-011 前置 | done（2026-09-03） |
| T-403 | 全局布局与状态总览：AppShell 侧边导航七页 + 全局状态条（采集/编译/大脑聚合、索引触发） | REQ-403 | — | T-011 | todo |
| T-404 | 编译页：状态/触发/Review/手动工具 lint-dedup-enrich（能力对齐旧页面） | REQ-404 | — | T-011 | todo |
| T-405 | 问答页 FR-030：brain query/search、带引用回答、引用跳转来源（条目原文/素材） | REQ-405 | — | T-011/T-115 | todo |
| T-406 | 知识库浏览页：五类列表+详情（Markdown/[[wikilink]] 跳转/frontmatter 面板）+ index/log 视图（移植 llm_wiki wiki-reader） | REQ-406 | ADR-015 | T-011/T-115 | todo |
| T-407 | 图谱页 FR-031：brain graph JSON→graphology→sigma.js v3（Web Worker 布局/高亮/详情/缩放控件，移植 graph-view）；增强 Louvain 着色/筛选/搜索 | REQ-407 | ADR-010/015 | T-011/T-115 | todo |
| T-408 | 素材管理与采集控制页 FR-040：素材列表/状态标记/预览（后端补 materials mark/content API）+ 各源启停/手动导入/网页抓取 | REQ-408 | — | T-011 | todo |
| T-409 | 知识管理页 FR-041：编辑写回/删除确认（后端补 PUT/DELETE /api/knowledge + brain.remove 索引一致性） | REQ-409 | — | T-011 | todo |
| T-410 | 设置页 FR-042：LLM API/embedding/监听目录/采集/编译/大脑配置节（后端扩展 settings：brain 节 + llm_api_key 只写不回读），持久化重启生效 | REQ-410 | — | T-011 | todo |
| T-411 | 端到端验收（「提问→带引用回答→跳转来源→查看图谱」闭环 + 能力覆盖不回退）+ 旧 static 下线 + 文档同步 | REQ-411 / §13 | — | M4 收尾 | todo |

## M2/M4 移植待办（llm_wiki → KnowSeq，ADR-015）

> 依据 ADR-015：编译层移植 nashsu/llm_wiki（GPL v3）ingest 内核到 Python，展示层升级 React 并直接移植其组件，插件参考其 MV3 扩展。参考源码本地化于 `reference/llm_wiki`（.gitignore 已排除，仅个人自用不分发）。移植文件头部注明 `Ported from nashsu/llm_wiki (GPL-3.0)`。

| ID | 描述 | 关联 REQ | 关联 ADR | 覆盖规划级 | 状态 |
|---|---|---|---|---|---|
| T-114 | M2 编译层移植：llm_wiki `src/lib/` ingest 内核 → Python `app/compile/`（两步 CoT / ingest-queue 持久化队列 / SHA256 增量缓存 / dedup 去重 / context-budget / CJK 清洗 / llm-client 多供应商路由 / enrich-wikilinks / lint / review-store）；保留 KnowSeq 自有部分（inbox 适配、五类条目 schema、config、FastAPI 触发） | FR-010/011 | ADR-008/015 | T-009 | done | 2026-09-03 |
| T-115 | M4 控制台 React 化：React 19 + Vite + TS 重构前端，移植 llm_wiki 知识库展示组件（wiki 浏览/wikilink/frontmatter）与图谱组件（sigma.js + graphology + ForceAtlas2）；FastAPI 后端不变 | FR-030/031/040~042 | ADR-010/015 | T-011 | todo |
| T-116 | Chrome 剪藏插件（MV3）：交互参考 llm_wiki `extension/`，通信改接 KnowSeq FastAPI 网页抓取/手动导入端点（替代其 clip_server） | REQ-108/109 延伸 | ADR-007/015 | T-006/T-007 延伸 | todo |

## 扩展点备忘

| ID | 描述 | 依据 | 状态 |
|---|---|---|---|
| T-113 | meeting 源 meta 记录说话人（speaker）与时间戳，支持"谁说的"溯源（7B 版输出自带该字段；BitNet 1.5B 解码器是否保留待实测，若不含则暂为纯转写） | ADR-014 | todo |

## 下一步

1. **M2 编译层完成（2026-09-03，T-214 端到端验收 31/31 通过，M2 关闭）**：真实 LLM（火山方舟 deepseek-v4-flash）全链路——3 条素材编译出 9 条五类条目 + index/log + sources 引用；二次编译幂等（compiled 标记）与缓存命中路径；lint/dedup/enrich 走通；控制台 compile 8 端点全流程。端到端发现并修复：DeepSeek 推理系列（含火山 ark 等 OpenAI 兼容端点）结构化输出默认关 thinking（llm_client._apply_reasoning 泛化，enrich JSON 契约不再被长推理拖慢/超时）。
2. **M3 大脑层完成（2026-09-03，T-306 端到端验收 19/19 通过，M3 关闭）**：LightRAG（lightrag-hku 1.5.7）对 knowledge/ 建向量索引+知识图谱+引用溯源——BrainEngine 同步门面（内部专用事件循环线程）、索引增量幂等（rel doc_id+内容哈希）、语义检索（naive）、带引用问答（hybrid 等）、图谱导出（nodes/edges JSON）、brain API 5 端点 + 控制台大脑面板。**embedding 用本地模型**（bge-small-zh-v1.5，ModelScope 下载到 models/embed/，sentence-transformers CPU）——用户无 embedding API，全本地向量化；问答/实体抽取复用云端 dsv4flash。真实验收：语义检索命中剪贴板条目、问答带引用、31 节点图谱。
3. **M4 交互层进行中（T-011/T-115，细分 T-401~411）**：React 化前端（问答/图谱/知识库/编译/素材/采集控制/设置），FastAPI 后端不变；图谱可视化按 ADR-010 修订版/ADR-015 落定的 **sigma.js 系**执行（sigma.js v3 + @react-sigma/core + graphology + graphology-layout-forceatlas2 + graphology-communities-louvain；M3 graph JSON 已就绪，前端转换为 graphology Graph）；需求拆分见 m4-requirements.md（REQ-401~411）。
4. **补 M1 遗留**：飞书凭据（app_id/app_secret）就绪后联调 T-106（T-004，REQ-106 验收前提）；T-113 待转写输出 JSON schema 确认后处置（若含 speaker/timestamp 字段则扩展 meeting 源 meta）。
