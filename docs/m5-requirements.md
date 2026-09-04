# M5 桌面化与会议实时捕获需求拆分（REQ-501 ~ REQ-509）

> 日期：2026-09-04　|　对应里程碑：M5（桌面化 + 会议实时捕获 + Windows 集成完善 + 演示打磨）　|　覆盖规划级任务：T-012
> 依据：ADR-016（Tauri 壳方案 A + 悬浮控件）、ADR-017（WASAPI 系统声音捕获）、ADR-014（转写链路）、ADR-011（Windows 集成）、architecture.md、milestones.md M5 验收标准
> 上游依赖：M4 已关闭——控制台七页就绪、单源启停 API（`/api/start|stop/{name}`）就绪、meeting 转写链路（asr_infer 子进程）就绪

---

## §0 范围与前置决策

### 0.1 目标

M5 四条主线：

1. **会议实时捕获**：真实会议场景（腾讯会议等）下直接抓取系统声音（对方发言）转写入库——补齐 ADR-014 只能"拖文件离线转写"的缺口，配桌面悬浮开始/结束按钮。
2. **桌面化**：Tauri 2.x 壳承载 Web 控制台（方案 A：WebView 加载本机 URL，后端零改动），关窗后台常驻，并为 sidecar 打包（方案 B）留好演进口子。
3. **Windows 集成完善**：注册表右键菜单（纳入采集/立即结束）、开机自启（原 M5 规划保留项）。
4. **演示打磨**：演示数据与演示脚本，从零跑通全链路。

### 0.2 前置决策（本里程碑固化）

| # | 决策 |
|---|------|
| D1 | **壳方案 A，零后端改动**：Tauri 2.x 主窗口 WebView 直接加载 `http://127.0.0.1:8765`；FastAPI 独立进程，壳不打包 dist、不管理后端生命周期；Origin 即本机地址，server.py Host/Origin 校验天然放行（ADR-016 决策 1） |
| D2 | **Rust 工具链为壳工程前置依赖**：本机未安装 cargo/rustc，M5 开工前须安装 rustup + MSVC Build Tools（T-502 前置检查项，非项目代码依赖） |
| D3 | **sidecar 演进口子三条预留（本次只留不实现）**：①`webui/src/api.ts` base 预留 `import.meta.env.VITE_API_BASE` 前缀位；②server.py Host/Origin 校验处注释 B 方案迁移说明（需放行 `tauri.localhost`）；③tauri.conf.json 预留 `externalBin`/sidecar 配置位注释（ADR-016 决策 4） |
| D4 | **会议实时捕获走 WASAPI loopback 直采（pyaudiowpatch）**：Python 侧新增 `system_audio` 源，分段 wav → 复用 ADR-014 asr_infer 转写链路；麦克风混音可选默认关；Meetily 式 Rust 捕获列为不选对照（ADR-017） |
| D5 | **壳与 pystray 托盘并存**：pystray（Python）负责采集开关与后端退出（现状保留）；壳侧负责窗口管理（关主窗=隐藏，壳托盘可重新显示/退出壳）；防多实例参考 Meetily #476（ADR-016 决策 3） |
| D6 | **开机自启对象 = 后端服务（run.py，含托盘）**，不含 Tauri 壳；与既有 `web.auto_start`（启动即开采集）是两回事，新增 `app.autostart` 配置项 + 设置页开关（HKCU Run 键，无需管理员） |
| D7 | **原 M5 规划项沿用既有方案**：右键菜单 = 注册表 HKCU（ADR-011）；演示形态 = 演示数据 + 演示脚本；不因 M5 扩展改变其实现路线 |

### 0.3 不在 M5 范围（裁剪）

- **方案 B：sidecar 打包 Python 后端**——仅留口子（D3），打包/分发实施另行启动
- **会议软件 SDK（腾讯会议等）**——用系统声音捕获通用路线，不做 SDK 集成
- **声纹分离/说话人溯源（T-113）**——待 BitNet 转写输出 schema 确认后处置（ADR-014 遗留，与 M5 独立）
- **全局快捷键**——默认不做（原规划"可选"项，需要时再评估）
- **飞书联调（T-106/T-004）**——M1 遗留，凭据就绪后补做，不占 M5
- **实时逐句转写上屏**——分段落盘近实时即可，逐句实时不做

### 0.4 与现有约定对齐

- 环境：Node v22.9.0 已确认；Python venv 就绪；**cargo/rustc 未安装**（D2 前置）
- API 风格：沿用既有端点——单源启停 `/api/start|stop/{name}`（T-408）、状态聚合 `/api/status`、settings 校验先行（422 不做部分写入）
- 安全：Host/Origin 本机校验中间件原样生效（D1 方案 A 下壳内访问 Origin 即本机，不受影响）；新增端点继续走该中间件
- 采集源注册范式：沿用 meeting_source 模式——引擎/依赖未就绪 → 状态 error 带提示，不影响其他源

---

## §1 REQ-501 系统声音捕获源（T-501）

| 项 | 内容 |
|----|------|
| 描述 | 新增 `app/capture/system_audio_source.py`：pyaudiowpatch 抓默认输出设备 WASAPI loopback 混音 → 定长分段落 wav（默认 5 分钟/段，可配）→ 每段经 asr_infer 转写 → `write_material(source=meeting)` → `inbox/meeting/`，meta 标记 `system-audio` |
| 接口 | 采集管理器注册源名 `system_audio`（启停走既有 `/api/start\|stop/system_audio`、状态并入 `/api/status`）；config 新增 `sources.system_audio.{enabled, segment_seconds, include_mic}`；stop 时收尾转写最后一段（不足分段时长立即落盘）；include_mic=true 时麦克风与 loopback 混为单 wav（默认 false） |
| 适配点 | 转写完全复用 meeting_source 的 asr_infer 子进程调用（引擎/模型未就绪 → 状态 error 降级，同 ADR-014 模式）；loopback 只含扬声器输出（不含自己麦克风声音）；默认输出设备切换（蓝牙耳机回连）时重建捕获流；控制台采集页加该源开关卡片；分段/静音检测参数参考 Meetily（Reference: Zackriya-Solutions/meetily (MIT)） |
| 验收 | 播放一段系统声音（会议录音/视频）→ 开始捕获 → 结束后 `inbox/meeting/` 产出转写稿且 meta 含 `system-audio` 标记；分段按配置落盘依序转写；停止收尾最后一段；include_mic=false 时无自己麦克风声音；引擎未就绪时 error 提示不影响其他源 |

> **验收记录（2026-09-04，T-501）**：五条全过——TTS 播放系统声音 → `inbox/meeting/` 产出 3 个转写稿（meta 均含 `capture: system-audio` 及 audio/duration_sec/engine/model_dir，内容与 TTS 文本吻合）；分段依序落盘转写（seg003→004→005 时间戳严格递增）；停止收尾最后一段（22.3s 不足满段立即落稿）；include_mic=false 无麦克风杂音；引擎未就绪 error 降级（提示含 ADR-014 构建指引，不影响其他源）。实现要点：静音哨兵流保 WASAPI 共享模式活跃（无活跃 render 流时 loopback read 阻塞）；纯静音段峰值检测跳过转写（防 asr_infer 无输出误报）。

## §2 REQ-502 Tauri 壳骨架（T-502）

| 项 | 内容 |
|----|------|
| 描述 | 新建 `shell/` Tauri 2.x 工程（Rust src-tauri + 最小配置）：主窗口 WebView 加载 `http://127.0.0.1:8765`，承载现有控制台 |
| 接口 | 主窗口配置（标题 KnowSeq / 尺寸 / 图标）；启动时探测后端（GET `/api/status`），未就绪显示内置提示页「请先启动 KnowSeq 后端（run.py）」而非白屏，就绪后加载/刷新到控制台 |
| 适配点 | 后端零改动（D1）；壳不打包 dist、不管后端生命周期；前置 D2 Rust 工具链；开发态 `tauri dev`，产物 `tauri build`（NSIS/MSI，本里程碑仅自用不分发） |
| 验收 | 壳窗口内完成「提问→带引用回答→跳转来源→查看图谱」闭环，与浏览器形态等价；后端未启动时壳内有明确提示；恶意 Host/Origin 仍 403（中间件行为不变） |

## §3 REQ-503 桌面体验：关窗隐藏与防多实例（T-503）

| 项 | 内容 |
|----|------|
| 描述 | 主窗关闭 = 隐藏（后端与采集继续运行）；防多实例（二次启动聚焦已有窗口）；壳托盘：重新显示主窗 / 退出壳；与 pystray 托盘职责分离（D5） |
| 接口 | Tauri 窗口 close 事件 → hide；`tauri-plugin-single-instance` 防多实例；壳托盘 TrayIcon（显示/退出）；pystray 侧现状不变（采集开关 + 后端退出） |
| 适配点 | 退出语义分级：关窗/退出壳不停后端；彻底停止 = pystray 退出后端（现状入口保留）；配置参考 Meetily 关窗隐藏 #471 与防多实例 #476（Reference: Zackriya-Solutions/meetily (MIT)） |
| 验收 | 关主窗后 `/api/status` 仍可达、采集不中断；壳托盘可重新唤出主窗；二次启动壳不产生第二实例（聚焦已有）；pystray 退出后端后壳侧提示后端离线 |

## §4 REQ-504 悬浮开始/结束控件（T-504）

| 项 | 内容 |
|----|------|
| 描述 | 常驻桌面透明小窗（始终置顶、可拖拽移动、不占任务栏）：两按钮「开始 / 结束」控制会议系统声音捕获（REQ-501 源启停） |
| 接口 | Tauri 第二窗口：`transparent + alwaysOnTop + decorations:false + skipTaskbar`；拖拽区域 `data-tauri-drag-region`；窗口加载 `http://127.0.0.1:8765/#/floating`——webui 新增极简 `/floating` 路由（两按钮 + 状态色点，复用 api.ts 与设计 tokens），保证 Origin 为本机从而通过 Host/Origin 校验；按钮调用既有 `POST /api/start\|stop/system_audio` |
| 适配点 | 结束 = stop 源 + 收尾转写最后一段（REQ-501 语义）；按钮态与源状态联动（running/ stopped）；悬浮窗显隐由壳托盘菜单/快捷方式控制；不新增后端端点 |
| 验收 | 悬浮按钮常驻所有窗口最前、可拖拽到任意位置；点「开始」→ `/api/status` 中 system_audio running、按钮态变化；点「结束」→ 最后一段收尾转写落库；任务栏无该窗口；透明背景无白底 |

## §5 REQ-505 sidecar 演进口子（T-505）

| 项 | 内容 |
|----|------|
| 描述 | 落实 D3 三条预留：api.ts 前缀位、server.py 迁移注释、tauri.conf.json sidecar 注释位——本次行为零变化 |
| 接口 | ①`webui/src/api.ts`：请求 base 改为 `` `${import.meta.env.VITE_API_BASE ?? ''}` `` 前缀（默认空串）；②server.py Host/Origin 校验处注释：方案 B 需放行 `tauri.localhost`；③tauri.conf.json：`externalBin`/sidecar 配置位以注释说明启用方式（打包 Python 后端为子进程） |
| 适配点 | 不改变任何现有请求路径与响应；三处口子均有注释指向 ADR-016 决策 4，B 方案启动时可检索 |
| 验收 | 控制台全部请求行为与现状一致（回归：问答/图谱/采集/设置页正常）；代码检索可见三处口子注释；`VITE_API_BASE` 未设置时构建产物行为不变 |

> **验收记录（2026-09-04，T-505）**：三处口子全部落地且互相指向 ADR-016 决策 4——①`webui/src/api.ts` `const API_BASE = import.meta.env.VITE_API_BASE ?? ''`（默认空串=相对路径，请求路径与现状一致）；②`app/web/server.py` Host/Origin 校验中间件处注释方案 B 迁移说明（WebView Origin 变为 `http://tauri.localhost` 时放行）；③`shell/src-tauri/tauri.conf.json` 占位骨架含 `externalBin` 注释位（PyInstaller 后端打包为 sidecar 子进程说明）。**行为零变化验证**：`npm run build` 通过（tsc + vite，新 bundle index-DAMhUBt-.js）+ `py_compile` server.py 通过 + `/` 托管新 bundle；浏览器回归四页全过——/ask（提问区/模式选择/状态栏）、/capture（六源卡片含系统声音「采集中·引擎就绪」、素材库）、/graph（337 节点 · 544 关系渲染 + 工具栏/图例）、/settings（六分组表单回显）；console 无当前 bundle 错误（历史累积日志均属旧构建与后端重启窗口期）。

## §6 REQ-506 注册表右键菜单（T-506）

| 项 | 内容 |
|----|------|
| 描述 | 原规划保留（ADR-011）：资源管理器右键文件夹 → 「纳入 KnowSeq 采集」（加入文件监听并启动 file 源）/「立即结束采集」（停止全部采集） |
| 接口 | HKCU\Software\Classes\Directory\shell\KnowSeq* 注册表项（无需管理员）；命令行触发后端能力——优先复用本地 HTTP（新端点 `POST /api/file_dirs/append`、`POST /api/stop_all`）+ 极薄命令行触发器（curl/python -c 或独立小脚本）；或后端提供 CLI 子命令 |
| 适配点 | 纳入采集 = `sources.file.dirs` 追加 + start file 源（持久化到 config.yaml，对齐设置页 file_dirs 语义）；安装/卸载右键菜单做成设置页按钮或脚本（写/删注册表键） |
| 验收 | 右键文件夹 → 纳入采集 → 该目录变更进入 `inbox/file/`（file 源 running）；「立即结束」停止全部采集；设置页 file_dirs 与右键添加的目录一致；卸载后注册表项清除 |

## §7 REQ-507 开机自启（T-507）

| 项 | 内容 |
|----|------|
| 描述 | 后端服务开机自启（D6：自启 run.py 含托盘，不含壳）；设置页开关控制写/删 HKCU Run 键 |
| 接口 | config 新增 `app.autostart`（默认 false）+ settings API 字段（校验先行，对齐 T-410 范式）+ 设置页"系统"分组开关；实现 = HKCU\Software\Microsoft\Windows\CurrentVersion\Run 写/删 `KnowSeq` 项（pythonw 静默启动 run.py，工作目录对齐项目根） |
| 适配点 | 与既有 `web.auto_start`（启动即开采集，D6 区分说明）互不影响——自启后是否立即开采集仍由 web.auto_start 决定；无需管理员权限 |
| 验收 | 开启开关 → 注册表键写入 → 重启系统后后端自动运行（托盘在、8765 可达）；关闭开关 → 键删除 → 重启不再自启；重启系统后采集行为符合 web.auto_start 配置 |

## §8 REQ-508 演示数据与演示脚本（T-508）

| 项 | 内容 |
|----|------|
| 描述 | 可重复的演示路径：演示数据集（示例素材）+ 演示脚本（从零跑通 采集→编译→索引→问答/图谱），支撑里程碑验收与对外演示 |
| 接口 | `scripts/demo/`（演示脚本 + 种子数据清单）；脚本按序执行：注入演示素材到 inbox（独立标记便于清理）→ 触发编译 → 触发大脑索引 → 输出预设问题清单与预期答案要点 |
| 适配点 | 不污染真实数据：演示素材带统一 meta 标记，脚本提供清理模式（演示产物可一键移除，含 inbox/knowledge/索引清理）；LLM/转写依赖沿用现有 config（引擎未就绪时跳过会议环节并提示） |
| 验收 | 全新环境按 README 步骤跑演示脚本全链路走通（采集→编译→问答带引用→图谱）；清理模式运行后数据回到演示前状态 |

## §9 REQ-509 端到端验收与文档同步（T-509）

| 项 | 内容 |
|----|------|
| 描述 | M5 整体验收（§11 清单逐项）+ 文档同步（changelog/tasks/milestones）+ M5 关闭 |
| 接口 | — |
| 适配点 | 验收以真实桌面环境为准（真实会议声音/真实重启自启/真实右键操作）；验收中发现的问题回补对应 REQ 后复验 |
| 验收 | §11 全部通过；changelog.md 留痕、tasks.md 状态更新、milestones.md M5 标记完成 |

---

## §10 依赖与工具链枚举

| 类别 | 项 | 说明 |
|------|----|------|
| Python 新增 | pyaudiowpatch | WASAPI loopback 捕获（REQ-501），Windows 专属 |
| Rust 工具链（前置） | rustup + MSVC Build Tools | 本机未安装，T-502 前置检查（D2） |
| 壳工程依赖（Rust） | tauri 2.x、tauri-plugin-single-instance | REQ-502/503 |
| webui 侧 | 无新增依赖 | `/floating` 路由复用既有设计系统与 api.ts（REQ-504）；api.ts 仅加 base 前缀位（REQ-505） |
| 系统 | HKCU 注册表（右键菜单/自启） | 无需管理员权限（REQ-506/507） |

## §11 整体验收

1. **会议实时捕获主线**：播放真实会议音频 → 悬浮按钮「开始」→ 会议进行（多段自动落盘转写）→ 「结束」收尾 → `inbox/meeting/` 产出带 `system-audio` 标记的转写稿 → 编译 → 问答可引用。
2. **桌面化主线**：壳窗口内控制台闭环与浏览器等价；关窗后台常驻、单实例、壳托盘唤出；pystray 采集开关不受影响。
3. **Windows 集成**：右键菜单纳入文件夹采集/立即结束生效；开机自启后端随系统启动。
4. **口子就位**：sidecar 三处口子可检索、行为零变化；B 方案迁移路径在 ADR-016 有据可查。
5. **回归**：浏览器访问控制台仍可用；既有五源采集/编译/大脑链路无回退；Host/Origin 校验仍拦截恶意请求。

## §12 待办映射

| REQ | 细分待办 |
|-----|----------|
| REQ-501 | T-501 |
| REQ-502 | T-502 |
| REQ-503 | T-503 |
| REQ-504 | T-504 |
| REQ-505 | T-505 |
| REQ-506 | T-506 |
| REQ-507 | T-507 |
| REQ-508 | T-508 |
| REQ-509 | T-509 |
