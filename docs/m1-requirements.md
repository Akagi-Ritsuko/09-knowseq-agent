# M1 采集层需求拆分（docs/m1-requirements.md）

> M1 的详细需求文档。顶层需求见 [prd.md](prd.md)（FR-001~006、FR-040/042/050 的 M1 部分）；本文档拆分为可执行的 REQ-101~111，并列出待办映射（[tasks.md](tasks.md) T-101~112）。
> 需求编号规则见 [ai-collab.md](ai-collab.md) §4。

## §0 范围与目标

**目标**：五类输入（会议音频、对话-微信企微/飞书、文件、网页、手动）全部打通，统一写入 `inbox/`；极简控制台可用；托盘开关雏形可用。

**不在 M1 范围**：编译层（M2）、大脑层 LightRAG（M3）、完整 Web 控制台与问答/图谱（M4）、右键菜单/快捷键/自启（M5）。

**前置决策**：① 极简控制台（FastAPI 先行，ADR-012）；② 飞书真实端到端联调（凭据就绪后）；③ 会议音频用 VibeVoice-ASR-BitNet 本地离线转写（ADR-014，取代 ADR-003 的 screenpipe 方案；屏幕画面 OCR 移出 M1 范围）。

## §1 工程与配置基础（REQ-101）

| 项 | 内容 |
|---|---|
| 描述 | 建立可运行的 Python 工程骨架与配置体系 |
| Python | 本机默认 `python`=2.7 过旧，**统一用 `py -3`** 建虚拟环境：`py -3 -m venv .venv`（2026-09-02 实测本机 `py -3` 为 Python 3.14，依赖已全部兼容安装） |
| 依赖 | fastapi、uvicorn、watchdog、pystray、pillow、requests、readability-lxml、lark-oapi、pyyaml、python-dotenv；可选组件（REQ-104 用）：VibeASR.cpp 引擎 + gguf 模型（VibeVoice-ASR-BitNet，本地构建 + 子进程调用；Windows 需 MinGW-w64，MSVC 不支持），不进主依赖 |
| 配置 | `config.yaml`（非敏感：目录、开关、监听目录、来源启用项）；`.env`（敏感：飞书 App ID/Secret、后续 LLM Key） |
| 目录 | `app/{main.py, config.py, capture/, web/, tray.py}` + 运行期 `inbox/` |
| 验收 | `py -3 -m venv .venv` 后能安装依赖并 `import` 各模块；`config.py` 能加载 `config.yaml` + `.env` 并持久化修改 |

## §2 inbox 素材模型（REQ-102，对应 ADR-013）

- 目录：`inbox/<source>/`，source ∈ {meeting, clipboard, feishu, file, web, manual}。
- 素材文件：单个 `.md`，文件名 `<source>_<yyyyMMdd_HHmmss>_<短id>.md`。
- frontmatter：`id`、`source`、`captured_at`（ISO）、`meta`（来源标识：URL/会话/文件名/等）、`compiled: false`（供 M2 消费）。
- 去重：clipboard/web/manual 用内容哈希（去重指纹存 `inbox/.dedup.json`）；meeting/feishu/file 按事件/文件天然去重。
- 接口：`app/capture/inbox.py` 提供统一 `write_material(source, title, content, meta)`，所有采集源调用。
- 验收：各源调用 `write_material` 后生成规范文件；重复内容不重复落盘；Obsidian 可直接打开。

## §3 采集管理（REQ-103）

- `app/capture/manager.py`：统一启停各采集源、聚合状态。
- 状态机：每源 `stopped / running / error`；提供 `start_all()/stop_all()/get_status()`。
- 开关由托盘与控制台共用。
- 验收：start/stop 能正确启动/终止各源线程；状态聚合准确；异常源标记 error 不拖垮整体。

## §4~§9 各采集源

### REQ-104 会议音频转写（FR-001，ADR-014）
- 输入：会议/通话录音等音频文件（wav 等；拖入热文件夹或手动导入触发）。
- 处理：子进程调用 VibeASR.cpp 的 `asr_infer`（VibeVoice-ASR-BitNet，本地 CPU 推理，4 线程 RTF<1），转写结果组装为 Markdown；说话人/时间戳字段以引擎实际输出为准（1.5B 解码器，待实测）。
- 输出：`write_material(source=meeting)`，meta 记音频文件名/时长/引擎与模型名。
- 约束：模型约 1.58GB；Windows 构建需 MinGW-w64；中文会议 WER 偏高（AliMeeting 40.58），质量以实测为准；MIT，官方声明仅供研发用途。
- 异常：引擎未构建/模型未下载 → 状态 error 并提示，不影响其他源；转写失败不落空文件。
- 验收：拖入一段会议录音后 `inbox/meeting/` 产出转写素材；引擎未就绪时不拖垮其他源。

### REQ-105 剪贴板监控（FR-002）
- 输入：剪贴板文本。处理：Windows 剪贴板轮询（周期可配），去重（REQ-102），非文本忽略，超长截断（上限可配，默认 50k 字符）。
- 输出：`write_material(source=clipboard)`，meta 记 `captured_from=clipboard`。
- 验收：复制文本后自动进入 `inbox/clipboard/`；重复复制不重复入库；复制图片/文件被忽略。

### REQ-106 飞书（FR-003）
- 输入：飞书群聊/单聊消息、云文档。处理：lark-oapi 机器人事件，WebSocket 长连接模式（无需公网回调）；消息 → `write_material(source=feishu)`（meta 含会话标识/发送者）；云文档提供导出导入接口。
- 前置：用户提供自建应用凭据（App ID/Secret + 事件订阅配置），写入 `.env`。
- 异常：凭据缺失 → 控制台设置页提示，状态 error 或 stopped。
- 验收（凭据就绪后真联调）：发消息/收消息后自动写入 `inbox/feishu/`；云文档可导入。

### REQ-107 文件监听（FR-004）
- 输入：配置目录中新增/修改的文档（md/txt/docx/pdf，先支持 md/txt，docx/pdf 解析按需）。处理：watchdog 监听 → 读取文本 → `write_material(source=file)`（meta 记原路径）。
- 热文件夹：`inbox/manual/` 或配置的 drop 目录，拖入即入库（批量）。
- 验收：向监听目录新增文件后自动进入 `inbox/file/`；拖入多个文件批量入库。

### REQ-108 网页抓取（FR-005）
- 输入：URL。处理：requests 抓取 → readability-lxml 抽取正文 → `write_material(source=web)`（meta 记 URL）。
- 异常：抓取失败/反爬 → 返回错误信息，不落空文件。
- 验收：输入有效 URL 后 `inbox/web/` 出现带 URL 来源的正文素材；无效 URL 报错。

### REQ-109 手动导入（FR-006）
- 输入：控制台粘贴文本 / 上传文件。处理：→ `write_material(source=manual)`。
- 验收：粘贴文本入库；上传文件入库；完成后素材列表可见。

## §10 极简控制台（REQ-110，对应 ADR-012）

- 后端：FastAPI 本地服务（`app/web/server.py`），仅本机监听。
- 页面（`app/web/static/` 极简单页）：采集状态、一键开关、手动导入表单、素材列表、设置（飞书凭据、监听目录、各源开关）。
- API：`GET /api/status`、`POST /api/start|stop`、`POST /api/import`（文本/文件）、`GET /api/materials`、`GET|POST /api/settings`。
- 验收：浏览器访问 `http://127.0.0.1:<port>` 完成"粘贴文本→入库→列表可见→开关采集"闭环。

## §11 托盘雏形（REQ-111，FR-050 子集）

- pystray 托盘：左键单击开始/结束采集；右键菜单（开始采集/结束采集/打开控制台/退出）。
- 依赖：pystray + pillow。
- 验收：托盘常驻；左键切换采集开关；右键菜单各动作生效。

## §12 非功能与配置清单

**NFR 落地要点**
- NFR-001 本地优先：采集、存储、处理全部本机；仅飞书 API 调用出网。
- NFR-002 隐私：飞书 App Secret、后续 LLM Key 只放 `.env`，不入日志、不入 inbox 内容。
- NFR-003 轻量：无重型运行时；采集源按需启用。
- NFR-006 可恢复：inbox 只追加；`compiled` 标记保证可重跑（M2 用）。

**配置项枚举（config.yaml + .env）**

| 键 | 位置 | 说明 |
|---|---|---|
| `web.port` | config.yaml | 控制台端口，默认 8765 |
| `sources.meeting.enabled` | config.yaml | 会议音频转写开关 |
| `sources.meeting.engine_path` | config.yaml | VibeASR.cpp `asr_infer` 可执行文件路径 |
| `sources.meeting.model_dir` | config.yaml | gguf 模型目录（VibeVoice-ASR-BitNet） |
| `sources.clipboard.enabled` | config.yaml | 剪贴板监控开关 |
| `sources.clipboard.interval` | config.yaml | 轮询间隔（秒） |
| `sources.clipboard.max_len` | config.yaml | 文本截断上限 |
| `sources.feishu.enabled` | config.yaml | 飞书开关 |
| `sources.file.dirs` | config.yaml | 监听目录列表 |
| `sources.file.drop_dir` | config.yaml | 热文件夹 |
| `sources.web.enabled` | config.yaml | 网页抓取开关 |
| `FEISHU_APP_ID` | .env | 飞书应用 ID |
| `FEISHU_APP_SECRET` | .env | 飞书应用密钥 |
| `FEISHU_VERIFICATION_TOKEN` | .env | 事件验证 token |
| `LLM_API_KEY`（M2 用） | .env | 云端 LLM Key 占位 |

## §13 M1 整体验收

1. 五类输入均能产出带来源标记的素材进 `inbox/<source>/`（REQ-104~109 验收齐）。
2. 极简控制台可手动导入 + 查看素材 + 开关采集（REQ-110）。
3. 托盘左键开关全部采集（REQ-111）。
4. 飞书真实消息 → `inbox/feishu/`（凭据就绪后真联调，REQ-106）。
5. 配置持久化、重启生效（REQ-101/110）。
6. 无业务代码在 M2 之前的重复工作：编译/索引不在此阶段。

## §14 待办映射

| 待办 | 需求 | 关联 ADR | 规划级任务 |
|---|---|---|---|
| T-101 | REQ-101 | — | T-002~008 前置 |
| T-102 | REQ-102 | ADR-013 | T-002~008 前置 |
| T-103 | REQ-103 | — | T-002~008 前置 |
| T-104 | REQ-104 | ADR-014 | T-002 |
| T-105 | REQ-105 | ADR-004 | T-003 |
| T-106 | REQ-106 | ADR-005 | T-004 |
| T-107 | REQ-107 | ADR-006 | T-005 |
| T-108 | REQ-108 | ADR-007 | T-006 |
| T-109 | REQ-109 | — | T-007 |
| T-110 | REQ-110 | ADR-012 | T-008 前置 |
| T-111 | REQ-111 | ADR-011 | T-008 |
| T-112 | M1 端到端验收 + 文档同步 | — | M1 收尾 |
