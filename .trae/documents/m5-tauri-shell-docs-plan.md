# M5 扩展：Tauri 桌面壳 + 系统声音捕获会议转写 —— 文档落地计划

## Summary

按用户决策：**方案 A 起步 + 留好 sidecar 口子**、**扩展 M5 范围**、**全套需求拆分**、**系统声音捕获与壳并列纳入**、**WASAPI 直采路线**。本次**只做文档落地**（不改代码、不装 Rust、不建壳工程）：

1. 新建 **ADR-016**（accepted）：Tauri 桌面壳方案 A + sidecar 演进口子（修订 ADR-010）
2. 新建 **ADR-017**（accepted）：会议实时捕获输入侧——WASAPI loopback 直采（扩展 ADR-014，转写引擎复用）
3. 新建 **m5-requirements.md**：M5 全范围需求拆分 REQ-501~508
4. 更新 **milestones.md / tasks.md / architecture.md / ADR-010 / ADR-014 / changelog.md**（+README 如有）
5. **本地 commit**（严禁 push）

## Current State Analysis

- **M4 已关闭**（2026-09-03）：React 七页 + dist 托管 + SPA fallback，浏览器访问 `http://127.0.0.1:8765`
- **会议转写现状**（[meeting_source.py](d:/learning_code/09-knowseq-agent/app/capture/meeting_source.py)）：唯一入口为 drop 热文件夹（10s 轮询音频文件 → `asr_infer.exe` VibeVoice-ASR-BitNet 转写 → `inbox/meeting/`）；**无** loopback/麦克风录音/任何会议软件集成（grep 确认 0 处）
- **ADR-010**（accepted）记录「Tauri 桌面壳：更重 → 不选」；底部有「修订：ADR-015」先例格式
- **ADR-014**（accepted）为会议音频转写 ADR（asr_infer 子进程链路）——本次输入侧扩展的基座
- **M5 现状**：「Windows 集成完善 + 演示打磨 —— 未开始」，交付物=右键菜单/全局快捷键(可选)/开机自启/演示；规划级任务 T-012（todo）
- **编号惯例**：M4→REQ-401~411/T-401~411，本批为 **REQ-5xx/T-5xx**；ADR 已用到 015 → **ADR-016/017**
- **环境**：Node v22.9.0 ✓；**cargo/rustc 未安装**（文档写为壳的前置依赖）；pyaudiowpatch 未在依赖中（捕获任务实施时安装）

## 核心决策（写入文档）

### ADR-016 —— Tauri 桌面壳（方案 A）

- **决策**：Tauri 2.x 壳，主窗口 WebView 加载 `http://127.0.0.1:8765`；FastAPI 后端照旧独立进程；壳不打包 dist、不管后端生命周期；**后端零改动**
- **sidecar 演进口子三条（B 方案迁移路径，本次固化成文）**：
  1. 前端 API base 注入点：`api.ts` 相对路径保持，预留 `import.meta.env.VITE_API_BASE` 前缀位
  2. 后端 Host/Origin 白名单迁移说明：B 方案需在 server.py 白名单加 `tauri.localhost`（文档化，A 方案不改）
  3. tauri.conf.json 结构预留：`externalBin`/sidecar 配置位与生命周期挂点写入需求文档
- **壳与 pystray 关系**：pystray 托盘继续管采集开关；Tauri 关闭=隐藏窗口（不退后端）；壳不自启后端
- **备选**：B 全量 sidecar 打包（演进非首选，成本在 PyInstaller 打包 Python 重依赖）/ Electron（体积大）/ 维持纯浏览器（现状）

### ADR-017 —— 会议实时捕获输入侧（WASAPI 直采）

- **决策**：新增系统声音采集源：**WASAPI loopback**（pyaudiowpatch）抓扬声器输出 → 分段落 wav → **复用现有 asr_infer 转写链路**（ADR-014，引擎不变）；来源标记区分（如 `source: system-audio`）；麦克风混音为**可选配置项**（默认关：仅对方声音；开启则 loopback+mic 混音为单轨）
- **备选**：screenpipe 音频源（ADR-003 集成位在，但需常驻第三方引擎）/ 腾讯会议 API（个人版无开放 API，不可行）/ 维持拖文件（现状）
- **限制如实写入**：loopback 只含扬声器输出（对方+本机外放）；说话人分离仍受 T-113（speaker 字段）约束

## Proposed Changes

### 1. 新建 `docs/adr/ADR-016-tauri-shell.md`（status: accepted, date: 2026-09-03）

按 ADR 模板：背景（M4 后纯浏览器形态体验缺口；ADR-010 当时否决理由与现在动机变化）/ 决策（方案 A + 口子三条 + 托盘关系）/ 备选与理由 / 后果（需 Rust 工具链【未安装，前置】；部署形态=桌面窗口为主浏览器保留；dist 仍由后端托管）/ 关联（修订 ADR-010；M5；T-012；相关 ADR-011）

### 2. 新建 `docs/adr/ADR-017-audio-capture.md`（status: accepted, date: 2026-09-03）

背景（会议转写现状=纯拖文件，腾讯会议等实时场景缺口）/ 决策（WASAPI loopback 直采 + 复用 asr_infer）/ 备选与理由 / 后果（新增 pyaudiowpatch 依赖；分段落盘与转写队列衔接；T-113 说话人约束不变）/ 关联（扩展 ADR-014；M5；相关 ADR-003/006）

### 3. 更新 `docs/adr/ADR-010-frontend.md` / `docs/adr/ADR-014-vibevoice-asr.md`

- ADR-010「修订」行追加：ADR-016（访问形态——新增 Tauri 桌面壳方案 A，浏览器保留；FastAPI+React 交互层决策不变）
- ADR-014 加「修订」行：ADR-017（输入侧——新增系统声音 WASAPI loopback 捕获源，转写引擎链路不变）

### 4. 新建 `docs/m5-requirements.md`（REQ-501~508，对齐 m4-requirements.md 格式）

- §0 范围与前置决策：
  - 目标：M5 改名「桌面化 + 会议实时捕获 + Windows 集成完善 + 演示打磨」
  - 前置决策表：D1 Tauri 方案 A 零后端改动 / D2 Rust 工具链前置安装 / D3 sidecar 口子三条 / D4 WASAPI 直采路线（pyaudiowpatch+复用 asr_infer，麦克风可选混音默认关）/ D5 壳与 pystray 并存、关闭隐藏 / D6 开机自启对象=后端服务 / D7 原 Windows 集成沿用现状
  - 不在范围：B 方案 sidecar 打包分发（演进项）、腾讯会议 SDK/API、说话人声纹分离（T-113）、壳内打包 dist、跨平台、全局快捷键（维持原 M5 可选项，默认不做）
- REQ-501（T-501）**系统声音捕获源**：`app/capture/system_audio_source.py`——pyaudiowpatch WASAPI loopback、分段落 wav（时长/静音切分策略）、接入采集管理器（启停/状态）、产出 `inbox/meeting/`（来源标记 system-audio）→ 复用 asr_infer 转写链路；config 开关（设备选择/分段参数/麦克风混音）；采集控制页加开关（对齐既有源模式）
- REQ-502（T-502）**Tauri 壳工程骨架（方案 A）**：`src-tauri/`（tauri 2.x）、rustup+MSVC 前置、窗口加载 `http://127.0.0.1:8765`、`npm run tauri dev/build`、应用图标
- REQ-503（T-503）**桌面体验**：窗口规格（标题 KnowSeq/默认尺寸与最小尺寸/单实例）、关闭隐藏到后台（后端不受影响）
- REQ-504（T-504）**sidecar 演进口子**：三条口子按上文落地（api.ts 注入点为唯一前端微改，行为不变；白名单迁移说明与 conf 预留文档化）
- REQ-505（T-505）**注册表右键菜单**（原 M5）：文件夹纳入采集 / 立即结束采集
- REQ-506（T-506）**开机自启**（原 M5）：后端服务自启（注册表 Run 键或启动项）；壳不自启后端
- REQ-507（T-507）**演示数据与演示脚本**（原 M5）：脚本覆盖系统声音捕获→转写→问答闭环
- REQ-508（T-508）**端到端验收 + 文档同步**：桌面窗口跑通「提问→带引用回答→跳转来源→查看图谱」；系统声音捕获真实会议场景出转写稿；右键/托盘入口可用；收尾文档

### 5. 更新 `docs/milestones.md`（M5 节重写）

- 标题：`## M5 桌面化 + 会议实时捕获 + Windows 集成完善 + 演示打磨 —— 未开始`
- 引用块：详细需求见 m5-requirements.md（REQ-501~508）与 tasks.md（T-501~508 / T-012）；决策依据 ADR-016/017
- 交付物加：Tauri 桌面壳（方案 A）、系统声音捕获转写源；验收加：桌面窗口完成既有闭环、真实会议声音产出转写稿

### 6. 更新 `docs/tasks.md`

- T-012 描述改为 M5 全范围（桌面化+会议实时捕获+Windows 集成+演示），关联加 ADR-016/017
- 新增「## M5 细分待办（实施顺序）」表：T-501~508（对齐 REQ-501~508，状态全 todo）
- 「下一步」追加：M5 规划扩展落地（ADR-016/017：Tauri 壳方案 A + WASAPI 系统声音捕获，需求拆分见 m5-requirements.md）

### 7. 更新 `docs/architecture.md`（ai-collab.md §2 要求 ADR 后同步）

- §2.1 采集层：补「系统声音 WASAPI loopback 捕获源（ADR-017，M5 起）」
- §2.4 交互层：补「桌面访问：Tauri 壳（ADR-016，M5 起）加载同一本地服务」
- §6 部署形态：补桌面窗口形态

### 8. 更新 `docs/changelog.md`

追加一行：`2026-09-03 | M5 规划扩展：Tauri 桌面壳方案 A（ADR-016，修订 ADR-010）+ 系统声音 WASAPI 捕获会议转写（ADR-017，扩展 ADR-014）+ REQ-501~508 需求拆分 + milestones/tasks/architecture 同步 | docs/… | T-012 / M5 / ADR-016/017`

### 9. README.md 检查

读 README，若有 M5/状态表述则同步；无则不动

### 10. 本地 commit（严禁 push）

```
git add docs/adr/ADR-016-tauri-shell.md docs/adr/ADR-017-audio-capture.md docs/adr/ADR-010-frontend.md docs/adr/ADR-014-vibevoice-asr.md docs/m5-requirements.md docs/milestones.md docs/tasks.md docs/architecture.md docs/changelog.md [README.md 如有改动]
git commit -m "docs: M5 扩展——Tauri 壳方案 A（ADR-016）+ 系统声音捕获转写（ADR-017）+ REQ-501~508 拆分"（多 -m 补充）
git log --oneline -3 验证（预期 a353f9a → 新 commit）
```

## Assumptions & Decisions

- **本次只写文档**：不安装 Rust/pyaudiowpatch、不建 src-tauri、不改任何代码（用户明确「先文档落地」）
- ADR-016/017 直接 `accepted`（方案与路线已由用户本轮拍板，视为讨论收敛；先例：ADR-010 等落地即 accepted）
- Tauri 版本写 2.x stable；跨平台/签名/自动更新不在范围
- 全局快捷键维持原 M5「可选」定位，默认不做（需求文档明确标注）
- 会议捕获的转写复用 asr_infer 同步链路——分段 wav 逐个走现有转写流程，不引入新引擎

## Verification

1. 交叉引用无错链：ADR-016↔ADR-010、ADR-017↔ADR-014、M5↔T-012/T-501~508↔REQ-501~508↔changelog
2. tasks.md「下一步」、milestones.md M5、m5-requirements.md 三处 M5 名称一致（「桌面化 + 会议实时捕获 + Windows 集成完善 + 演示打磨」）
3. `git status` 干净、`git log` 出现新 commit 且**无 push**
4. 「方案 A 后端零改动」与「转写引擎复用」两个结论在 ADR/m5-requirements 中表述一致（口子与捕获均为后续实施项，非本次代码改动）
