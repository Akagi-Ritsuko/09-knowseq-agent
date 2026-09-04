# KnowSeq Agent —— 智能知识采集与知识图谱大脑

本地轻量运行的 AI 知识管理 Agent：**自动无感采集**多源知识（屏幕/音频、对话、文件、网页、手动导入），由**云端 LLM 提炼**为结构化知识，经 **LightRAG** 构建"向量检索 + 知识图谱"大脑，提供带**引用溯源**的问答与图谱可视化，通过 **Windows 托盘/右键菜单**一键开关采集。

> 本项目从 `08-trae-memory-compiler` skill 扩展而来：其"对话 → 结构化知识库"的编译思想（记录/编译/查询/体检）是本项目**编译层**的设计源头。区别在于：skill 依赖 Trae 环境，本项目是**独立可运行的本地程序**。

## 文档导航

| 文档 | 一句话用途 |
|---|---|
| [docs/user-guide.md](docs/user-guide.md) | **使用指南：安装、启动、各功能页与采集源用法（面向使用者）** |
| [docs/ai-collab.md](docs/ai-collab.md) | AI 协作约定：如何读文档、每次改动必须同步更新哪些文档 |
| [docs/prd.md](docs/prd.md) | 需求规格：功能清单、范围边界、验收标准 |
| [docs/architecture.md](docs/architecture.md) | 架构说明：分层架构、数据流、技术栈、部署形态 |
| [docs/milestones.md](docs/milestones.md) | 里程碑：M0-M5 阶段规划与验收 |
| [docs/tasks.md](docs/tasks.md) | 任务进度追踪（当前状态第一入口） |
| [docs/changelog.md](docs/changelog.md) | 变更日志（每次修改留痕） |
| [docs/adr/](docs/adr/) | 架构决策记录（ADR-001 ~ ADR-017） |

## 当前状态速览

- **里程碑**：M4（交互层）已完成（2026-09-03）；M5（桌面化 + 会议实时捕获 + Windows 集成完善 + 演示打磨）规划就绪（2026-09-04，实施未开始，前置 Rust 工具链）；阶段规划见 [milestones.md](docs/milestones.md)
- **近期变更**：见 [changelog.md](docs/changelog.md)
- **待办入口**：见 [tasks.md](docs/tasks.md)

## 快速上手（给新接触者/AI）

1. 读 [docs/ai-collab.md](docs/ai-collab.md) —— 先了解协作与更新约定
2. 读 [docs/architecture.md](docs/architecture.md) —— 理解整体架构
3. 读 [docs/tasks.md](docs/tasks.md) —— 看当前要做什么
