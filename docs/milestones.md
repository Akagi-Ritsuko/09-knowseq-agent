# 里程碑（docs/milestones.md）

> 里程碑为阶段规划，**不承诺具体排期**。每个里程碑有目标 / 交付物 / 验收标准；完成一个再进入下一个。

## M0 文档与项目骨架 —— 已完成（2026-09-02）

- **目标**：建立面向 AI 协作的文档体系，让任何 AI 能快速理解项目并留痕。
- **交付物**：README、docs/ai-collab、docs/prd、docs/architecture、docs/milestones、docs/tasks、docs/changelog、docs/adr（11 条）。
- **验收**：文档间引用一致；changelog 有本次落地记录；tasks.md 将 M0 任务标为 done；无业务代码。

## M1 采集层 —— 核心完成（2026-09-02，飞书联调除外）

> 已拆分详细需求与待办：见 [m1-requirements.md](m1-requirements.md)（REQ-101~111）与 [tasks.md](tasks.md)（T-101~112）。
> 2026-09-02 真实桌面验收全部通过：meeting 音频转写（VibeVoice-ASR-BitNet + asr_infer.exe，ADR-014，真实录音拖入 drop 热文件夹产出转写稿）、剪贴板自动入库、文件监听、网页抓取、手动导入、控制台各页面、托盘开关采集。唯一遗留：飞书机器人联调（T-004/T-106）待凭据就绪后补做；T-113（说话人/时间戳字段）待转写输出 schema 确认后处置。

- **目标**：五类输入全部打通，统一写入 `inbox/`，极简控制台 + 托盘开关雏形可用。
- **交付物**：
  - 会议音频转写接入（VibeVoice-ASR-BitNet，本地 CPU 实时）
  - 剪贴板监控（微信/企微对话）
  - 飞书机器人事件（WebSocket 长连接）+ 云文档导入
  - watchdog 文件监听 + 拖拽/批量导入
  - 网页 URL 抓取正文
  - 手动导入（粘贴文本/拖入文件）
  - 托盘图标：左键开始/结束采集
- **验收**：各采集源产出能进入 `inbox/` 且带来源标记；托盘可开关全部采集；设置可配监听目录。

## M2 编译层 —— 已完成（2026-09-03）

> 详细需求与待办：见 [m2-requirements.md](m2-requirements.md)（REQ-201~214）与 [tasks.md](tasks.md)（T-201~214 / T-114）。
> 2026-09-03 T-214 端到端验收 31/31 通过：真实 LLM（火山方舟 deepseek-v4-flash）编译 3 条素材产出 9 条五类条目 + index/log + sources 引用；二次编译幂等 + 缓存命中；lint/dedup/enrich 走通；控制台 compile 8 端点全流程。端到端发现并修复：DeepSeek 推理系列（含火山 ark）结构化输出默认关 thinking（`_apply_reasoning` 泛化）。

- **目标**：`inbox/` 新素材 → 云端 LLM 提炼为结构化知识条目。
- **交付物**：`app/compile/` 全模块（两步 CoT 提炼、持久化队列、SHA256 缓存、幂等标记、上下文预算、CJK 清洗、五类 schema、lint、review、dedup、enrich-wikilinks）、控制台编译 API 与编译页、自动+手动触发。
- **验收**：重复执行不重复产出（compiled 标记 + 缓存双条件）；每条产出带来源引用（frontmatter sources）；`knowledge/` 结构符合约定（Markdown + wikilinks，五类目录 + index/log）。

## M3 大脑层 —— 已完成（2026-09-03）

> 详细需求与待办：见 [m3-requirements.md](m3-requirements.md)（REQ-301~306）与 [tasks.md](tasks.md)（T-301~306）。
> 2026-09-03 T-306 端到端验收 19/19 通过：LightRAG 1.5.7 对 knowledge/ 建向量索引+知识图谱+引用溯源；本地 embedding（bge-small-zh-v1.5，用户无 embedding API 决策）+ 云端 dsv4flash 问答；语义检索命中、带引用问答、31 节点图谱、brain API 全端点。

- **目标**：LightRAG 接入，向量索引 + 知识图谱 + 引用溯源。
- **交付物**：`app/brain/`（BrainEngine 同步门面：索引/检索/问答/图谱）、config `brain:` 节（embedding 本地或云端 OpenAI 兼容）、brain API 5 端点 + 控制台大脑面板。
- **验收**：能对 `knowledge/` 语义检索；图谱可生成（nodes/edges JSON）；回答带引用。

## M4 交互层 —— 未开始

- **目标**：本地 Web 控制台可用。
- **交付物**：FastAPI 后端 + 轻量前端（问答页、图谱页、采集控制、素材与知识管理、设置页）。
- **验收**：浏览器打开本地地址完成"提问→带引用回答→跳转来源→查看图谱"闭环。

## M5 Windows 集成完善 + 演示打磨 —— 未开始

- **目标**：体验完善 + 可演示。
- **交付物**：注册表右键菜单（把文件夹纳入采集/立即结束）、全局快捷键（可选）、开机自启、演示数据与演示脚本。
- **验收**：右键/快捷键/托盘三入口均可开关与纳入采集；演示脚本跑通。
