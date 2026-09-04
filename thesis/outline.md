# 硕士学位论文大纲（outline）

> 论文题目：**《基于大语言模型的多源知识采集与知识图谱问答系统的设计与实现》**
> 培养类型：学术硕士（学硕）→ 第 6 章包含 LightRAG 五种检索模式对比实验
> 系统原型：KnowSeq Agent（本仓库 d:\learning_code\09-knowseq-agent）
> 本大纲定稿日期：2026-09-05（对应 docs/tasks.md T-013）

---

## 1. 总体目标与字数分配

正文（第 1~7 章，不含摘要/参考文献/附录）合计 **≥ 30000 字**，目标约 40500 字。
字数统计口径：正文中文字符，不含代码块、表格、图、参考文献。

| 章 | 标题 | 目标字数 |
|---|---|---|
| 第 1 章 | 绪论 | 5000 |
| 第 2 章 | 相关理论与技术 | 5000 |
| 第 3 章 | 系统需求分析 | 4500 |
| 第 4 章 | 系统总体设计 | 7000 |
| 第 5 章 | 系统详细设计与实现 | 12000 |
| 第 6 章 | 系统测试与结果分析 | 5000（含五模式对比实验） |
| 第 7 章 | 总结与展望 | 2000 |

## 2. 文件组织约定

- `thesis/outline.md` — 本大纲（唯一大纲真相源，章节调整须同步改此处）
- `thesis/ch01.md` ~ `thesis/ch07.md` — 各章正文，每章一个文件
- `thesis/abstract.md` — 中英文摘要与关键词（阶段 6 产出）
- `thesis/references.md` — 参考文献（GB/T 7714，阶段 6 定稿）
- 写作中遇到待核实事实，就地标注 `<!-- TODO-核实: ... -->`，统稿（T-607）时必须清零
- 初稿图表用 Mermaid / Markdown 表格落稿，均标注「终稿排版时重绘」；软件截图用 `[截图占位：...]` 占位
- 文中引用文献用 `[n]` 编号，与 references.md 对应

## 3. 各章结构、图表清单与素材映射

### 第 1 章 绪论（5000 字）

| 节 | 内容 | 字数 |
|---|---|---|
| 1.1 | 研究背景与意义：个人知识碎片化困境；多模态信息源（会议、网页、文档）难以沉淀；LLM 带来的自动化知识加工机遇；本地化/隐私诉求 | 1300 |
| 1.2 | 国内外研究现状：1.2.1 个人知识管理（PKM）工具的局限；1.2.2 LLM 与检索增强生成（RAG）[2][3]；1.2.3 大模型与知识图谱融合（GraphRAG、LightRAG、KG+LLM roadmap）[4][5][6][15]；1.2.4 语音识别本地化（Whisper、VibeVoice+BitNet CPU 推理）[7] | 1800 |
| 1.3 | 论文主要工作：四层架构（采集→编译→大脑→交互）；inbox 不可变模型与五类知识条目；编译层质量闭环；基于 LightRAG 的本地图谱问答；Windows 桌面集成与 Tauri 桌面壳 | 1200 |
| 1.4 | 论文组织结构 | 200 |

图表：图 1-1 系统总体概览（四层架构简图，Mermaid）；图 1-2 论文技术路线（问题→方案→验证）。
素材：README.md、docs/prd.md（背景与目标）、docs/architecture.md、ADR-008。

### 第 2 章 相关理论与技术（5000 字）

| 节 | 内容 | 字数 |
|---|---|---|
| 2.1 | 大语言模型基础：Transformer [1]、注意力机制、提示工程、API 调用与本地推理的权衡 | 900 |
| 2.2 | 检索增强生成（RAG）与混合检索：naive RAG [2]、RAG survey [3]、GraphRAG [5]、LightRAG 的双层检索（KG + 向量）与增量索引 [4] | 1100 |
| 2.3 | 知识图谱与图可视化：KG 表示/构建/应用综述 [11][15]；力导布局 ForceAtlas2 [10]；Louvain 社区发现 [9] | 800 |
| 2.4 | 本地语音识别：ASR 流程与 WER 指标；Whisper [7]；量化压缩（BitNet）；公开测试集 AISHELL-4 [13]、AliMeeting [14] | 800 |
| 2.5 | Windows 音频回环采集：WASAPI loopback 原理（pyaudiowpatch） | 500 |
| 2.6 | Web 服务与前端技术：FastAPI 异步框架；React 19 + TypeScript + Vite；sigma.js v3 / graphology 图渲染 | 600 |
| 2.7 | 桌面应用打包：Tauri 2.x 架构（WebView + Rust 壳 + sidecar） | 200 |

图表：图 2-1 RAG→GraphRAG→LightRAG 演进对比（Mermaid）；图 2-2 本地 ASR 流水线（音频→分段→量化模型→文本）；表 2-1 相关技术选型一览。
素材：docs/architecture.md、ADR-009、ADR-014、ADR-017、user-guide.md。

### 第 3 章 系统需求分析（4500 字）

| 节 | 内容 | 字数 |
|---|---|---|
| 3.1 | 系统总体目标与用户场景（单用户本地部署；采集-沉淀-问答闭环） | 800 |
| 3.2 | 功能需求分析：按模块归纳——多源采集（六源：剪贴板/音频转写/文档导入/手动/网页/文件监听，REQ-101~105）、编译（REQ-201~204）、大脑（REQ-301~303）、问答（REQ-401~403）、前端七页（REQ-404~406）、Windows 集成（REQ-501~503） | 1800 |
| 3.3 | 非功能需求：本地隐私、幂等与可恢复、性能预算、可观测性（NFR-001~006） | 700 |
| 3.4 | 用例分析与数据流：核心用例图；一条素材从采集到问答的全生命周期 | 800 |
| 3.5 | 范围边界论证：明确不做多用户/云同步/移动端/实时协作的理由 | 300 |

图表：图 3-1 系统总体用例图（Mermaid）；图 3-2 素材全生命周期数据流（Mermaid）；表 3-1 功能需求汇总表（模块→需求编号→要点）。
素材：docs/m1-requirements.md（REQ-101~111、T-112 验收）、m2（REQ-201~214）、m3（REQ-301~306）、m4（REQ-401~411）、m5（REQ-501~509）、docs/prd.md（FR-001~052、NFR-001~006）、docs/user-guide.md。

### 第 4 章 系统总体设计（7000 字）

| 节 | 内容 | 字数 |
|---|---|---|
| 4.1 | 总体架构设计：四层架构（采集层→编译层→大脑层→交互层）与职责边界 | 1200 |
| 4.2 | 关键设计决策与权衡（ADR 提炼）：≥ 4 组对比表——①inbox 不可变追加模型 vs 就地编辑（ADR-013）；②编译层移植 nashsu/llm_wiki vs 自研（ADR-008/015，GPL-3.0 合规声明）；③知识引擎选型 LightRAG vs GraphRAG/自研（ADR-009/003→014）；④桌面壳 Tauri 方案 A（WebView+sidecar）vs Electron/方案 B（ADR-016）；⑤WASAPI loopback vs 虚拟声卡（ADR-017）；⑥BrainEngine 同步门面+asyncio 内部化（m3 D1~D6） | 2200 |
| 4.3 | 数据模型与存储设计：inbox 只追加 JSONL；compiled 五类条目（decision/lesson/concept/connection/query）；本地存储 JsonKV + NanoVectorDB + NetworkX；增量幂等索引（rel doc_id + 内容哈希）；上下文预算（字符制 15%/5%/50%） | 1600 |
| 4.4 | 模块划分与接口设计：server.py 路由表；app/capture、app/compile、app/brain、webui、shell 职责与调用关系 | 1200 |
| 4.5 | 技术栈选型与部署形态：技术栈表；本机运行 vs Tauri 桌面壳两种形态 | 600 |

图表：图 4-1 系统总体架构图（四层，Mermaid）；图 4-2 端到端数据流图；图 4-3 存储结构图（inbox/compiled/brain 三级）；表 4-1 ADR 权衡对比总表；表 4-2 模块-目录-职责表；表 4-3 技术栈选型表。
素材：docs/adr/ADR-001~017（重点 003/004/008/009/013/014/015/016/017）、docs/architecture.md、docs/m3-requirements.md（D1~D6）、m4（D1~D8）、server.py、app/ 目录结构。

### 第 5 章 系统详细设计与实现（12000 字，全文重心）

| 节 | 内容 | 字数 |
|---|---|---|
| 5.1 | 多源采集层实现：六源统一入口与 inbox 不可变追加；Win32 剪贴板监听与句柄截断 bug 修复（argtypes/restype 缺失，REQ-104 案例）；WASAPI loopback 直采（pyaudiowpatch，默认 300s 分段、静音检测、include_mic=false）；VibeVoice-ASR-BitNet 本地 CPU 转写（VibeASR.cpp asr_infer 子进程）；网页/文档/手动源 | 2600 |
| 5.2 | 知识编译层实现：移植声明（nashsu/llm_wiki，GPL-3.0，仅个人自用不分发）；九步编译流程与两步 CoT；持久化队列（429 暂停 15min、MAX_RETRIES=3）；SHA256 双条件缓存；上下文预算；lint/dedup/enrich/review 质量闭环；五类知识条目 schema | 2600 |
| 5.3 | 知识大脑层实现：LightRAG（lightrag-hku 1.5.7）集成；BrainEngine 同步门面与 asyncio 内部化；增量幂等索引（rel doc_id+内容哈希）；bge-small-zh-v1.5 本地 embedding；索引状态缺陷修复案例（54 条 parsing 卡死→state_saved 字段+超时 1800→7200s，m5 §9.2）；问答走火山方舟 deepseek-v4-flash | 2800 |
| 5.4 | 交互层实现：FastAPI 路由与错误处理；React 七页路由；sigma.js v3 + ForceAtlas2 + Louvain 社区着色；问答带引用→跳转来源→查看图谱闭环 | 2200 |
| 5.5 | Windows 集成与桌面壳实现：pystray 托盘；HKCU 右键菜单；开机自启（HKCU Run 键 + pythonw std 流 os.devnull 兜底）；Tauri 2.x 方案 A（WebView 加载 http://127.0.0.1:8765，sidecar 三条口子） | 1500 |

图表：图 5-1 采集层六源流程图；图 5-2 编译层九步流程图；图 5-3 大脑层索引/查询时序图；图 5-4 前端页面结构与图渲染流程；图 5-5 Tauri 桌面壳结构。每节配 1~2 段真实代码片段（10~30 行，摘自 app/、server.py、webui/、shell/，标注文件路径）。
素材：app/capture/、app/compile/、app/brain/、server.py、webui/src/、shell/、docs/m1（剪贴板 bug）、docs/m2（P1~P6、T-214 31/31）、docs/m3（D1~D6）、docs/m5 §9.2（索引缺陷）、docs/adr/ADR-004/014/016/017、docs/user-guide.md。

### 第 6 章 系统测试与结果分析（5000 字）

| 节 | 内容 | 字数 |
|---|---|---|
| 6.1 | 测试环境与方法：软硬件环境表；测试策略（里程碑验收 + 端到端演示 + 对比实验） | 600 |
| 6.2 | 功能测试：用例表 ≥ 20 条，与验收记录对应（M1 剪贴板、M2 编译 31/31、M3 大脑 19/19、M4 闭环、M5 Windows） | 1200 |
| 6.3 | 关键指标分析：索引速率约 0.7 条/分钟；图谱规模演进（31→337/544→585/1038）；ASR RTF 0.71、WER（AISHELL-4 27.45 / AliMeeting 40.58，注明 CPU 本地单次测试口径） | 800 |
| 6.4 | 端到端演示案例：scripts/demo 智慧大棚主题，4 份种子素材→编译→3 个预设问题的回答与引用展示 [截图占位] | 700 |
| 6.5 | LightRAG 五种检索模式对比实验（学硕要求）：naive/local/global/hybrid/mix；实验设计（同一 demo 索引、直接调用 /api/brain/query 的 mode 参数）；指标（引用命中率、响应时延、回答长度）；结果表与分析 | 1100 |
| 6.6 | 缺陷与修复案例：brain 索引状态不一致（m5 §9.2）；低电平英文幻觉、专有名词噪声、asr_infer 崩溃 exit 3221226505 等观察记录 | 400 |

图表：图 6-1 五模式对比实验流程；图 6-2 五模式指标柱状对比（Mermaid xychart 或表格）；表 6-1 测试环境；表 6-2 功能测试用例表（≥20 条）；表 6-3 五模式实验结果表；表 6-4 缺陷修复记录表。
素材：docs/m2（T-214）、m3（T-306）、m4（T-408/T-411）、m5（T-508、§9.2、§9.3）、scripts/demo/（run_demo.py、4 份种子素材、3 个预设问题）、docs/adr/ADR-014（WER/RTF）。实验数据须实跑获得，禁止编造。

### 第 7 章 总结与展望（2000 字）

| 节 | 内容 | 字数 |
|---|---|---|
| 7.1 | 工作总结：对照第 1 章主要工作逐条回收（含量化成果） | 900 |
| 7.2 | 不足与局限：单用户假设、WER 离场噪音表现、索引速率、前端性能上限 | 600 |
| 7.3 | 未来展望：多用户/云同步、增量学习、更轻 ASR、评测基准化 | 500 |

图表：表 7-1 论文工作与目标对照表；表 7-2 局限与改进方向表。
素材：README.md、docs/milestones.md（M0~M5）、各章回收。

## 4. 摘要与参考文献（阶段 6 产出）

- `thesis/abstract.md`：中文摘要 500~600 字 + 关键词 4~6 个（建议：大语言模型；知识图谱；检索增强生成；多源信息采集；本地部署）；英文 Abstract 与 Keywords 对应
- `thesis/references.md`：15~25 条，GB/T 7714 格式，文中 [n] 顺序编号

## 5. 参考文献候选池（均须逐条核实后引用，严禁编造）

1. Vaswani A, et al. Attention is all you need. NeurIPS 2017.
2. Lewis P, et al. Retrieval-augmented generation for knowledge-intensive NLP tasks. NeurIPS 2020.
3. Gao Y, et al. Retrieval-augmented generation for large language models: A survey. arXiv:2312.10997, 2023.
4. Huang X, et al. LightRAG: Simple and fast retrieval-augmented generation. arXiv:2410.05779, 2024.
5. Edge D, et al. From local to global: A graph RAG approach to query-focused summarization. arXiv:2404.16130, 2024.
6. Pan S, et al. Unifying large language models and knowledge graphs: A roadmap. IEEE TKDE, 2024.
7. Radford A, et al. Robust speech recognition via large-scale weak supervision (Whisper). ICML 2023.
8. Xiao S, et al. C-Pack: Packaged resources to advance general Chinese embedding. SIGIR 2024.（bge 系列依据）
9. Blondel V D, et al. Fast unfolding of communities in large networks. J. Stat. Mech., 2008.（Louvain）
10. Jacomy M, et al. ForceAtlas2, a continuous graph layout algorithm. PLoS ONE, 2014.
11. 徐增林, 等. 知识图谱技术综述. 电子科技大学学报, 2016.
12. 车万翔, 等. 大模型时代的自然语言处理. 中国科学:信息科学, 2023.
13. Fu M, et al. AISHELL-4: An open-source scenario-specific speech recognition and speech separation dataset. Oriental COCOSDA, 2021.
14. Chen Y, et al. AliMeeting: A dataset for far-field multi-channel meeting speech recognition. ICASSP, 2022.
15. Ji S, et al. A survey on knowledge graphs: Representation, acquisition and applications. IEEE TNNLS, 2022.

软件/工具类（可作 [EB/OL] 电子资源或脚注，引用前核实版本）：lightrag-hku（GitHub）、pyaudiowpatch（GitHub）、Microsoft VibeVoice、BitNet.cpp、Tauri 2.x、FastAPI、React、sigma.js、pystray。

## 6. 术语表（全文统一用词）

| 术语 | 含义（首次出现给英文原词） |
|---|---|
| inbox 源 | 采集层统一落盘的原始素材存储，只追加、不可变，经编译后打 compiled 标记 |
| 编译层 | 将 inbox 素材经 LLM 多步流程转化为结构化知识条目的模块（app/compile） |
| 五类知识条目 | decision / lesson / concept / connection / query |
| 大脑层 | 基于 LightRAG 的知识索引与检索问答模块（app/brain），BrainEngine 为其同步门面 |
| 双层检索 | LightRAG 同时利用知识图谱（实体/关系）与向量低层信息检索 |
| 幂等索引 | 相同 rel doc_id + 内容哈希不重复入库 |
| 上下文预算 | 编译时按字符比例（15%/5%/50%）约束 LLM 输入的机制 |
| WASAPI loopback | Windows 音频回环采集接口，用于系统声音直采 |
| VibeASR.cpp | 本地 CPU 转写子进程（asr_infer），VibeVoice+BitNet 量化模型 |
| RTF / WER | 实时率 / 词错误率，ASR 核心指标 |
| Tauri 方案 A | WebView 直接加载 http://127.0.0.1:8765，后端零改动 + sidecar 三条口子 |
| GraphRAG / LightRAG | 图结构化 RAG 方法 / 其轻量开源实现（lightrag-hku 1.5.7） |
| bge-small-zh-v1.5 | 本地中文 embedding 模型 |
| JsonKV / NanoVectorDB / NetworkX | 大脑层本地三元存储（KV / 向量 / 图） |

## 7. 学术诚信与事实红线（写作全程遵守）

1. **组件边界如实**：自研（server.py、app/ 各模块、webui/、shell/、demo 脚本）；移植（编译层流程移植自 nashsu/llm_wiki，GPL-3.0，仅个人自用不分发，论文如实标注）；现成库/模型（LightRAG、VibeVoice+BitNet、bge-small-zh-v1.5、FastAPI、React、sigma.js、Tauri、pyaudiowpatch、pystray）。
2. **量化数据必须溯源**：所有数字（31/31、19/19、337/544、585/1038、0.7 条/分钟、RTF 0.71、WER 27.45/40.58 等）须能在 docs/m*-requirements.md、docs/adr、代码或实验记录中找到出处；新实验数据（五模式对比）须实跑留档。
3. **参考文献严禁编造**：只引用第 5 节候选池中核实存在的条目；未核实前不得进正文。
4. **不得包含敏感信息**：API key、本机用户名、内网地址一律不得写入论文。
5. **图表纪律**：初稿 Mermaid/表格 + 「终稿排版时重绘」标注；截图用占位符。
6. **TODO-核实 清零**：统稿阶段全部解决，不得遗留。

## 8. 里程碑与任务对应

| 任务 | 内容 | 产出 |
|---|---|---|
| T-013 | 论文规划与大纲定稿（本文件） | thesis/outline.md |
| T-601 | 第 1 章绪论 + 第 2 章相关技术 | thesis/ch01.md、ch02.md |
| T-602 | 第 3 章需求分析 | thesis/ch03.md |
| T-603 | 第 4 章总体设计 | thesis/ch04.md |
| T-604 | 第 5 章详细设计与实现 | thesis/ch05.md |
| T-605 | 第 6 章测试与结果分析（含五模式实验实跑） | thesis/ch06.md、实验数据留档 |
| T-606 | 第 7 章 + 摘要 + 参考文献 | thesis/ch07.md、abstract.md、references.md |
| T-607 | 全文统稿：术语统一、TODO-核实 清零、README 增补 thesis/ 导航 | 全文定稿 |

范围外：学校模板排版、查重盲审、T-116/T-004/T-113 代码开发、演示截图实拍。
