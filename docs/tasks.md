# 任务进度追踪（docs/tasks.md）

> 当前状态第一入口。每次改动请同步更新本文档（见 ai-collab.md §2）。
> 状态：todo / doing / done。编号 T-三位数，递增不复用。

## 当前任务

| ID | 描述 | 关联 | 状态 | 完成日期 |
|---|---|---|---|---|
| T-001 | 落地项目文档体系（README/ai-collab/prd/architecture/milestones/tasks/changelog/ADR×11） | M0 | done | 2026-09-02 |
| T-002 | M1-采集层：screenpipe（屏幕+音频）接入 | M1 / ADR-003 | todo | |
| T-003 | M1-采集层：剪贴板监控（微信/企微） | M1 / ADR-004 | todo | |
| T-004 | M1-采集层：飞书机器人事件 + 云文档导入 | M1 / ADR-005 | todo | |
| T-005 | M1-采集层：watchdog 文件监听 + 拖拽/批量导入 | M1 / ADR-006 | todo | |
| T-006 | M1-采集层：网页 URL 抓取正文 | M1 / ADR-007 | todo | |
| T-007 | M1-采集层：手动导入（粘贴文本/拖入文件） | M1 | todo | |
| T-008 | M1-采集层：托盘图标左键开关采集雏形 | M1 / ADR-011 | todo | |
| T-009 | M2-编译层：云端 LLM 提炼流水线（inbox→知识条目） | M2 / ADR-008 | todo | |
| T-010 | M3-大脑层：LightRAG 接入（向量+图谱+引用溯源） | M3 / ADR-009 | todo | |
| T-011 | M4-交互层：FastAPI + 轻量前端（问答/图谱/控制/管理/设置） | M4 / ADR-010 | todo | |
| T-012 | M5-Windows 集成完善 + 演示打磨 | M5 / ADR-011 | todo | |

## M1 细分待办（实施顺序）

> 详细需求见 [m1-requirements.md](m1-requirements.md)（REQ-101~111）。规划级任务 T-002~T-008 由下列细分任务覆盖。

| ID | 描述 | 关联 REQ | 关联 ADR | 覆盖规划级 | 状态 |
|---|---|---|---|---|---|
| T-101 | 工程基础：venv(py -3)/依赖/目录骨架/config.yaml+.env/config.py | REQ-101 | — | T-002~008 前置 | todo |
| T-102 | inbox 写入服务与素材模型（write_material/去重/frontmatter） | REQ-102 | ADR-013 | T-002~008 前置 | todo |
| T-103 | 采集管理器：各源启停/状态聚合 | REQ-103 | — | T-002~008 前置 | todo |
| T-104 | screenpipe 接入（screenpipe-py，增量拉取→inbox/screen） | REQ-104 | ADR-003 | T-002 | todo |
| T-105 | 剪贴板监控（Windows 轮询+去重+截断） | REQ-105 | ADR-004 | T-003 | todo |
| T-106 | 飞书机器人事件（WebSocket 长连接）+ 云文档导入 | REQ-106 | ADR-005 | T-004 | todo |
| T-107 | watchdog 文件监听 + 热文件夹（拖拽/批量） | REQ-107 | ADR-006 | T-005 | todo |
| T-108 | 网页抓取（URL→readability 正文→inbox/web） | REQ-108 | ADR-007 | T-006 | todo |
| T-109 | 手动导入（控制台粘贴文本/上传文件） | REQ-109 | — | T-007 | todo |
| T-110 | 极简控制台（FastAPI + 状态/开关/导入/素材/设置页） | REQ-110 | ADR-012 | T-008 前置 | todo |
| T-111 | 托盘雏形（pystray 左键开关 + 右键菜单） | REQ-111 | ADR-011 | T-008 | todo |
| T-112 | M1 端到端验收 + 文档同步（changelog/tasks/milestones） | §13 | — | M1 收尾 | todo |

## 下一步

进入 **M1 采集层**：先做 T-101~T-103（工程与数据底座），再逐源 T-104~T-109，随后 T-110/T-111，最后 T-112 验收。
