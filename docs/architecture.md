# 架构说明（docs/architecture.md）

## 1. 架构总览

```
┌──────────────── 采集层（本地、无感、常驻）────────────────┐
│ 屏幕+音频   screenpipe（本地 OCR + Whisper）             │
│ 对话-微信/企微  剪贴板监控                               │
│ 对话-飞书   飞书开放平台机器人事件（WebSocket 长连接）    │
│              + 云文档导出导入                            │
│ 文件        watchdog 文件夹监听 + 拖拽/批量导入           │
│ 网页        URL 抓取正文（requests + 正文抽取）           │
│ 手动        粘贴文本 / 拖入文件                          │
│        ↓ 统一写入 inbox/（原始素材，只追加不修改）        │
├──────────────── 编译层（云端 LLM API）───────────────────┤
│ 增量提炼：inbox 新素材 → 结构化知识条目                  │
│ （决策 / 教训 / 概念 / 连接，复用 memory-compiler 思想）  │
│        ↓ 写入 knowledge/（Markdown + wikilinks）         │
├──────────────── 大脑层（现成组件 LightRAG）───────────────┤
│ 向量化（云端 embedding） + 自动知识图谱                  │
│ + 增量索引 + 引用溯源                                    │
│        ↓ API                                            │
├──────────────── 交互层（FastAPI 本地服务 + 轻量自研前端）─┤
│ 问答页(带引用)  图谱页(vis-network/ECharts)             │
│ 采集控制/状态  素材&知识管理  设置页                     │
└──────────────────────────────────────────────────────────┘
        ├─ Windows 托盘图标（pystray）：左键开关采集
        └─ 注册表右键菜单：把文件夹纳入采集 / 立即结束
```

## 2. 分层说明

### 2.1 采集层
- **职责**：多类输入 → 统一 `inbox/`，只追加不修改（源不可变原则，源自 memory-compiler 的 `daily/` 理念）。
- **屏幕/音频**：screenpipe（本地 OCR + Whisper，Windows 支持），存储本地 SQLite。
- **对话-微信/企微**：剪贴板监控（无官方 API 的现实路径）。
- **对话-飞书**：开放平台自建应用 + 机器人事件订阅（WebSocket 长连接，无需公网回调）+ 云文档导出导入。
- **文件**：watchdog 监听目录 + 拖拽/批量导入。
- **网页**：URL 抓取 + 正文抽取。
- **手动**：粘贴文本/拖入文件。

### 2.2 编译层
- **职责**：对 `inbox/` 新增素材，用云端 LLM 提炼为结构化知识条目，写入 `knowledge/`。
- 复用 memory-compiler 编译思想：决策（Decision）/ 教训（Lesson）/ 概念（Concept）/ 连接（Connection）。
- 幂等：以"已提炼标记"避免重复产出。

### 2.3 大脑层
- **职责**：对 `knowledge/` 建向量索引 + 知识图谱，提供检索与引用溯源。
- 采用现成组件 **LightRAG**（`lightrag-hku`），配置 OpenAI 兼容云端 API（LLM + embedding）。

### 2.4 交互层
- **职责**：本地 Web 控制台 + 问答/图谱界面 + 采集控制。
- 后端 FastAPI 本地服务；前端轻量自研，图谱用现成组件（vis-network / ECharts graph），编辑器可用 CodeMirror。

## 3. 数据流

| 环节 | 输入 | 处理 | 输出/存储 |
|---|---|---|---|
| 采集 | 屏幕/音频/剪贴板/飞书事件/文件/URL/手动 | 提取文本（本地） | `inbox/`（原始素材，追加式） |
| 编译 | `inbox/` 新素材 | 云端 LLM 提炼 | `knowledge/`（结构化条目） |
| 索引 | `knowledge/` | LightRAG 向量化 + 建图 | 向量库 + 图谱（LightRAG 存储） |
| 查询 | 用户问题 | LightRAG 检索 + LLM 生成 | 答案 + 引用溯源 |

## 4. 组件与技术选型

| 组件 | 选型 | 备注 |
|---|---|---|
| 后端框架 | Python + FastAPI | 本地服务 + API |
| 屏幕/音频采集 | screenpipe | 本地 OCR + Whisper，Windows 支持 |
| 文件监听 | watchdog | Python |
| 剪贴板监控 | 自研（轮询/钩子） | 微信/企微对话入口 |
| 飞书接入 | 飞书开放平台 SDK/API | WebSocket 长连接模式 |
| 网页抓取 | requests + 正文抽取 | 备选 readability |
| 大脑 | LightRAG（lightrag-hku） | 向量 + 图谱 + 引用溯源 |
| LLM/embedding | 云端 OpenAI 兼容 API | DeepSeek / Qwen / GLM |
| 系统托盘 | pystray | 左键开关采集 |
| 右键菜单 | 注册表 HKCU | 把文件夹纳入采集 |
| 图谱可视化 | vis-network / ECharts | 现成组件 |
| 编辑器 | CodeMirror（可选） | 前端知识编辑 |

## 5. 目录规划（代码侧，M1 起创建）

```
09-knowseq-agent/
  docs/                 # 文档（本仓库现阶段主体）
  app/
    main.py             # 入口：托盘 + FastAPI + 启动采集
    capture/            # 采集层（screenpipe/剪贴板/飞书/文件/网页）
    compile/            # 编译层（LLM 提炼）
    brain/              # 大脑层（LightRAG 封装）
    web/                # 交互层（FastAPI 路由 + 前端静态资源）
    config.py           # 设置（API Key 等，本地持久化）
  inbox/                # 原始素材（运行时生成）
  knowledge/            # 提炼后的知识条目（运行时生成）
```

> 说明：以上为规划形态，具体以里程碑实施时的 ADR/任务为准；现阶段仅创建 docs/。

## 6. 部署形态

- 本地常驻进程（托盘图标 + 后台采集），无需管理员权限。
- 浏览器访问 `http://127.0.0.1:<port>` 使用 Web 控制台。
- 仅 LLM/embedding 请求出网，其余全部本地。
