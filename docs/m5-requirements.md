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

> **验收记录（2026-09-04，T-502）**：验收三项全过（真机四场景）——①后端未启动有明确提示：壳启动加载 fallback 内置提示页（K logo + spinner），60s 截止后文案更新为「后端未就绪：请先启动 KnowSeq 后端（python run.py）。本窗口每 5 秒自动重试。」；②壳窗口内闭环与浏览器形态等价：后端启动后 ≤5s 重试周期内自动导航 `http://127.0.0.1:8765/`（location.replace）壳内渲染控制台（七入口 + 状态条「采集 6 源·编译·大脑 就绪」），提问「剪贴板采集有哪些坑？」→ ~30s 带内联引用回答（References 5 条 + 9 张引用卡）→ 点击引用卡 [2] 跳转 `/knowledge?path=lessons%2Fwin32-clipboard-handle-truncation.md` 条目详情完整（frontmatter/标签/关联/来源/正文）→ 图谱页 337 节点 · 544 关系壳内渲染正常；③恶意 Host/Origin 仍 403：`Host: evil.com` → 403、`Origin: http://evil.com` → 403（中间件行为不变）。`tauri build` 产物验证通过：NSIS `bundle/nsis/KnowSeq_0.1.0_x64-setup.exe` + MSI `bundle/msi/KnowSeq_0.1.0_x64_en-US.msi`。
>
> **偏差补记（2026-09-04，T-502 真机验收发现并修复）**：`probe_backend` 原用裸 `TcpStream::connect`（无连接超时），本机环境对无监听端口的 connect 会被安全软件代答 SYN-ACK（实测 ~2s 才返回、`Get-NetTCPConnection` 确认 8765 实无 LISTEN 进程），探测周期失真（每轮 ~3.3s、原 120 轮固定循环需 ~6.7 分钟才走到超时文案分支）。修复：`TcpStream::connect_timeout(800ms)` + 密集期改为 60s deadline 循环，60s 超时文案按预期出现。

## §3 REQ-503 桌面体验：关窗隐藏与防多实例（T-503）

| 项 | 内容 |
|----|------|
| 描述 | 主窗关闭 = 隐藏（后端与采集继续运行）；防多实例（二次启动聚焦已有窗口）；壳托盘：重新显示主窗 / 退出壳；与 pystray 托盘职责分离（D5） |
| 接口 | Tauri 窗口 close 事件 → hide；`tauri-plugin-single-instance` 防多实例；壳托盘 TrayIcon（显示/退出）；pystray 侧现状不变（采集开关 + 后端退出） |
| 适配点 | 退出语义分级：关窗/退出壳不停后端；彻底停止 = pystray 退出后端（现状入口保留）；配置参考 Meetily 关窗隐藏 #471 与防多实例 #476（Reference: Zackriya-Solutions/meetily (MIT)） |
| 验收 | 关主窗后 `/api/status` 仍可达、采集不中断；壳托盘可重新唤出主窗；二次启动壳不产生第二实例（聚焦已有）；pystray 退出后端后壳侧提示后端离线 |

> **验收记录（2026-09-04，T-503，真机四条全过）**：①**关窗隐藏后台常驻**——点主窗标题栏关闭 → `CloseRequested` 事件 `prevent_close()+hide()` 主窗消失；壳进程（pid 30744）存活、`/api/status` 仍可达（manager.running=True、素材数 36 不变=采集未中断）；EnumWindows 按 pid 枚举可见窗口仅剩悬浮控件与 SIW helper（主窗确已隐藏、非关闭）。②**壳托盘唤出主窗**——任务栏溢出区（「显示隐藏的图标」）点 KnowSeq 托盘按钮 → Win32 原生菜单弹出三项「显示主窗/悬浮控件/退出壳」，CheckMenuItem 勾选态与窗口实际可见性精确同步（主窗隐藏时「显示主窗」无勾、浮窗可见时「悬浮控件」勾上，`on_menu_event` 按 `is_visible()` 显式同步）；点「显示主窗」→ 主窗最大化回前台（EnumWindows rect (-8,-8) 1936x1048 最大化特征 + `GetForegroundWindow` 返回壳进程主窗句柄）。③**单实例**——再次启动 `knowseq-shell.exe`，4s 后 `Get-Process` 仍仅原进程（第二实例经 tauri-plugin-single-instance 退出并把焦点交还首实例，前台=主窗）。④**后端离线提示与恢复**——停后端进程 → probe 在线监测连续 2 次失败（低频期 ~15s）主窗自动导航 `http://tauri.localhost/?state=offline` 显示 fallback 离线页（K logo + 「与后端的连接已断开，采集已中断。请确认后端仍在运行（python run.py），恢复后本窗口会自动返回控制台。」+ spinner）；重启后端 → probe 成功自动导航回控制台（WebUI 完整渲染、采集状态 6 源）。验证方法论备注：Tauri 托盘菜单为 Win32 原生菜单，UIA 树不可见，以 PowerShell CopyFromScreen 截屏定位 + SendInput 物理点击完成操作；窗口隐藏/唤出以 EnumWindows 为权威验证。

## §4 REQ-504 悬浮开始/结束控件（T-504）

| 项 | 内容 |
|----|------|
| 描述 | 常驻桌面透明小窗（始终置顶、可拖拽移动、不占任务栏）：两按钮「开始 / 结束」控制会议系统声音捕获（REQ-501 源启停） |
| 接口 | Tauri 第二窗口：`transparent + alwaysOnTop + decorations:false + skipTaskbar`；拖拽区域 `data-tauri-drag-region`；窗口加载 `http://127.0.0.1:8765/#/floating`——webui 新增极简 `/floating` 路由（两按钮 + 状态色点，复用 api.ts 与设计 tokens），保证 Origin 为本机从而通过 Host/Origin 校验；按钮调用既有 `POST /api/start\|stop/system_audio` |
| 适配点 | 结束 = stop 源 + 收尾转写最后一段（REQ-501 语义）；按钮态与源状态联动（running/ stopped）；悬浮窗显隐由壳托盘菜单/快捷方式控制；不新增后端端点 |
| 验收 | 悬浮按钮常驻所有窗口最前、可拖拽到任意位置；点「开始」→ `/api/status` 中 system_audio running、按钮态变化；点「结束」→ 最后一段收尾转写落库；任务栏无该窗口；透明背景无白底 |

> **验收记录（2026-09-04，T-504，真机五条全过）**：①**常驻最前**——主窗最大化（rect 覆盖浮窗区域）时截屏可见浮窗叠于主窗内容之上（`alwaysOnTop` 生效）。②**可拖拽**——mcp drag 工具对非焦点窗口 image→screen 坐标映射失准（按窗口 origin=(0,0) 计算，落点错位）不适用；改 SendInput 物理拖拽（`SetCursorPos` 起点 + `mouse_event` DOWN/分步 move×5/UP），浮窗 (1760,249)→(1280,730) 位移与拖拽向量精确一致，EnumWindows 复核 L/T 落位无误。③**开始→running + 按钮态联动**——浮窗 toggle 两步 API（先 `POST /api/settings {system_audio_enabled:true}` 再 `POST /api/start/system_audio`），2s 状态轮询驱动 UI：标题「系统声音 · 采集中」+ 绿色状态点、「开始」禁用/「结束」可用，与 `/api/status` 中 system_audio running 一致。④**结束→收尾落库（机制全通，转写引擎崩溃定性记录）**——三次闭环实测（采集 107s/134s/269s 后点「结束」）：stop 触发 → 未满段收尾立即落盘（`inbox/.system_audio/` 三个收尾 wav 字节数 20,647,980/25,714,732/51,728,428 与时长精确对应）→ 入队转写（错误消息 Audio 路径指向收尾 wav，证明 `asr_infer` 被正确调用）→ 状态 stopped → 浮窗 UI 同步「已停止」+ 按钮翻转。三次收尾段转写均遇 VibeASR 引擎崩溃（exit 3221226505 / 0xC0000409 FAIL_FAST）——**定性非收尾链路缺陷**：收尾段与满段走完全相同 `_close_segment` 代码路径（T-501 已实证满段转写落库 36 条素材）、269s 接近满段时长排除时长因素；三次输入均为 Ring05.wav 提示音循环的高度重复音频，疑似引擎对重复内容的稳定性问题（T-501 期间 seg012 亦偶发崩溃一次）。落库链路有效性由 T-501 验收实证；引擎对重复音频崩溃留待后续对照实验（正常语音收尾段复验）。⑤**任务栏无窗 + 透明无白底**——`skipTaskbar` 生效（explorer 任务栏应用列表无浮窗按钮），透明背景 `useEffect` 置 html/body background=transparent 无白底闪现。
>
> **偏差补记（2026-09-04，T-504 实现时确认）**：接口栏所写 `/#/floating`（hash 路由）实为 `/floating`（BrowserRouter 路由 + FastAPI SPA fallback 兜底直达），WebView 加载 `http://127.0.0.1:8765/floating`，Origin 仍为本机通过 Host/Origin 校验（REQ-505 口子行为不变）。浮窗显隐由壳托盘菜单「悬浮控件」控制（CheckMenuItem 勾选态双向同步），需求栏「悬浮窗显隐由壳托盘菜单/快捷方式控制」取托盘菜单一路。

## §5 REQ-505 sidecar 演进口子（T-505）

| 项 | 内容 |
|----|------|
| 描述 | 落实 D3 三条预留：api.ts 前缀位、server.py 迁移注释、tauri.conf.json sidecar 注释位——本次行为零变化 |
| 接口 | ①`webui/src/api.ts`：请求 base 改为 `` `${import.meta.env.VITE_API_BASE ?? ''}` `` 前缀（默认空串）；②server.py Host/Origin 校验处注释：方案 B 需放行 `tauri.localhost`；③tauri.conf.json：`externalBin`/sidecar 配置位以注释说明启用方式（打包 Python 后端为子进程） |
| 适配点 | 不改变任何现有请求路径与响应；三处口子均有注释指向 ADR-016 决策 4，B 方案启动时可检索 |
| 验收 | 控制台全部请求行为与现状一致（回归：问答/图谱/采集/设置页正常）；代码检索可见三处口子注释；`VITE_API_BASE` 未设置时构建产物行为不变 |

> **验收记录（2026-09-04，T-505）**：三处口子全部落地且互相指向 ADR-016 决策 4——①`webui/src/api.ts` `const API_BASE = import.meta.env.VITE_API_BASE ?? ''`（默认空串=相对路径，请求路径与现状一致）；②`app/web/server.py` Host/Origin 校验中间件处注释方案 B 迁移说明（WebView Origin 变为 `http://tauri.localhost` 时放行）；③`shell/src-tauri/tauri.conf.json` 占位骨架含 `externalBin` 注释位（PyInstaller 后端打包为 sidecar 子进程说明）。**行为零变化验证**：`npm run build` 通过（tsc + vite，新 bundle index-DAMhUBt-.js）+ `py_compile` server.py 通过 + `/` 托管新 bundle；浏览器回归四页全过——/ask（提问区/模式选择/状态栏）、/capture（六源卡片含系统声音「采集中·引擎就绪」、素材库）、/graph（337 节点 · 544 关系渲染 + 工具栏/图例）、/settings（六分组表单回显）；console 无当前 bundle 错误（历史累积日志均属旧构建与后端重启窗口期）。
>
> **偏差补记（2026-09-04，T-502 实施时发现）**：tauri-build（build.rs 阶段）以严格 serde_json 解析 `tauri.conf.json`，**不支持 JSONC 注释**，T-505 预留的「externalBin 注释位」无法以注释形式留在该文件。口子注释迁移至 `shell/src-tauri/README.md`（含完整启用步骤）与 `shell/src-tauri/src/main.rs` 头注，三处口子仍互相指向 ADR-016 决策 4、可检索性不变；`tauri.conf.json` 改为纯 JSON。

## §6 REQ-506 注册表右键菜单（T-506）

| 项 | 内容 |
|----|------|
| 描述 | 原规划保留（ADR-011）：资源管理器右键文件夹 → 「纳入 KnowSeq 采集」（加入文件监听并启动 file 源）/「立即结束采集」（停止全部采集） |
| 接口 | HKCU\Software\Classes\Directory\shell\KnowSeq* 注册表项（无需管理员）；命令行触发后端能力——优先复用本地 HTTP（新端点 `POST /api/file_dirs/append`、`POST /api/stop_all`）+ 极薄命令行触发器（curl/python -c 或独立小脚本）；或后端提供 CLI 子命令 |
| 适配点 | 纳入采集 = `sources.file.dirs` 追加 + start file 源（持久化到 config.yaml，对齐设置页 file_dirs 语义）；安装/卸载右键菜单做成设置页按钮或脚本（写/删注册表键） |
| 验收 | 右键文件夹 → 纳入采集 → 该目录变更进入 `inbox/file/`（file 源 running）；「立即结束」停止全部采集；设置页 file_dirs 与右键添加的目录一致；卸载后注册表项清除 |

> **验收记录（2026-09-04，T-506，全部通过）**：①安装：设置页「安装右键菜单」→ HKCU\Software\Classes\Directory\shell\KnowSeq.Capture（默认值「纳入 KnowSeq 采集」）/KnowSeq.Stop（「立即结束采集」）两键写入，command 均指向 `scripts/context_menu.py`（pythonw 静默执行，免管理员）；②触发器等效验证：`context_menu.py capture <dir>` → POST /api/file_dirs/append → config.yaml `sources.file.dirs` 持久化 + file 源自动重启生效（FileSource 仅 start() 时 schedule watched_dirs，ADR-006 约束）；`context_menu.py stop` → POST /api/stop_all 六源全停；③右键「纳入 KnowSeq 采集」真机全链路：explorer 窗口 SendInput 右键 test2 → Win11 新式菜单「显示更多选项」→ 经典菜单点击 → file_dirs=[test,test2]（与设置页/API 一致）→ file 源 running → 投放 right-click-note2.md 增量入库（materials 38→39，watchdog 建立监听前已存在文件不回扫，增量语义符合 ADR-006）；④右键「立即结束采集」真机：六源全部 stopped；⑤卸载：uninstall → 两键清除 → 再 install 恢复（最终态=已安装）。
>
> **偏差补记（2026-09-04，T-506）**：①**SDK 右键缺陷与替代验收法**——SDK `click(element_id, button="right")` 两次均映射到 screen(0,0)（element→屏幕坐标换算失效）且纯坐标模式被 schema `required=["element_id"]` 拒绝，改用 Win32 SendInput 屏幕坐标法完成真机验收（EnumWindows 取 explorer 窗口 → GetWindowRect 比例换算 → SetForegroundWindow → mouse_event；前置坑：explorer 非前台时右键首击仅激活窗口不弹菜单）。②`POST /api/stop_all` 为 `/api/stop` 的语义命名别名（同调 `manager.stop_all()`），供右键触发器使用、自文档化。③顺带修复 T-501 遗留：设置页 `SOURCE_LABEL` 缺 `system_audio`（显示为原始键名）且保存 body 缺 `system_audio_enabled`（开关不落盘）；原「开机自启（托盘随系统启动）」label 实为 `web.auto_start` 语义，更名为「启动时自动开始采集」并与 T-507 新增自启开关区分。

## §7 REQ-507 开机自启（T-507）

| 项 | 内容 |
|----|------|
| 描述 | 后端服务开机自启（D6：自启 run.py 含托盘，不含壳）；设置页开关控制写/删 HKCU Run 键 |
| 接口 | config 新增 `app.autostart`（默认 false）+ settings API 字段（校验先行，对齐 T-410 范式）+ 设置页"系统"分组开关；实现 = HKCU\Software\Microsoft\Windows\CurrentVersion\Run 写/删 `KnowSeq` 项（pythonw 静默启动 run.py，工作目录对齐项目根） |
| 适配点 | 与既有 `web.auto_start`（启动即开采集，D6 区分说明）互不影响——自启后是否立即开采集仍由 web.auto_start 决定；无需管理员权限 |
| 验收 | 开启开关 → 注册表键写入 → 重启系统后后端自动运行（托盘在、8765 可达）；关闭开关 → 键删除 → 重启不再自启；重启系统后采集行为符合 web.auto_start 配置 |

> **验收记录（2026-09-04，T-507）**：①开启开关（默认 false）→ settings API `POST {"autostart":true}` → HKCU Run 键写入实证：`KnowSeq REG_SZ "…\.venv\Scripts\pythonw.exe" "…\run.py"`（pythonw 静默启动 run.py，D6 自启对象=后端含托盘）；②**等效开机执行通过**（模拟登录会话环境直接执行 Run 键等价命令）：`Start-Process pythonw run.py` → 8765 LISTENING + `/api/status` 正常 + pystray 托盘在 + 六源 running（`web.auto_start=true` 行为符合）；③关闭开关 → Run 键删除（reg query 报「找不到指定的注册表项或值」）。真重启验证（REQ-507 验收第 1/2 条的「重启系统后」环节）留 T-509 端到端验收补做。
>
> **偏差补记（2026-09-04，T-507，run.py pythonw 适配修复）**：等效开机执行排障发现 run.py 在 pythonw（无控制台，`sys.stdin/stdout/stderr` 全为 None）下两处崩溃——①`faulthandler.enable()` 依赖 stderr 抛 `RuntimeError: sys.stderr is None`；②修复①后仍 8765 不可达，py-spy dump 证实 uvicorn serve 线程静默死亡：uvicorn `ColourizedFormatter`（logging.py）在 `use_colors=None` 默认路径调用 `sys.stdout.isatty()`，stdout=None 抛 AttributeError，daemon 线程异常写到 None stderr 无处可去（其余线程健康、六源/托盘照常启动）。修复：run.py 入口层在 std 流为 None 时替换为 `os.devnull` 全局兜底（uvicorn/tqdm 等库均受益），`main.py` 零改动；另确认 venv `pythonw.exe` 为 launcher、spawn 系统真身双进程属正常结构，启动耗时约 30s（探活勿过早）。诊断产物 py-spy 已装入 venv。

## §8 REQ-508 演示数据与演示脚本（T-508）

| 项 | 内容 |
|----|------|
| 描述 | 可重复的演示路径：演示数据集（示例素材）+ 演示脚本（从零跑通 采集→编译→索引→问答/图谱），支撑里程碑验收与对外演示 |
| 接口 | `scripts/demo/`（演示脚本 + 种子数据清单）；脚本按序执行：注入演示素材到 inbox（独立标记便于清理）→ 触发编译 → 触发大脑索引 → 输出预设问题清单与预期答案要点 |
| 适配点 | 不污染真实数据：演示素材带统一 meta 标记，脚本提供清理模式（演示产物可一键移除，含 inbox/knowledge/索引清理）；LLM/转写依赖沿用现有 config（引擎未就绪时跳过会议环节并提示） |
| 验收 | 全新环境按 README 步骤跑演示脚本全链路走通（采集→编译→问答带引用→图谱）；清理模式运行后数据回到演示前状态 |

> **验收记录（2026-09-04，T-508）**：①`py_compile` 两脚本通过；②`run_demo.py` 全链路走通（运行中后端 127.0.0.1:8765，基线 materials=37/graph 337 节点）：前置三项检查 → 4 份种子经 `Inbox.write_material` 注入（`meta={demo:true, seed:文件名}`，标题带【演示】前缀，dedup=False 可重复运行）→ 编译队列清空 → 知识条目产出（第一轮 14 条/第二轮 17 条，concepts/lessons/queries/decisions/connections 五类，条目 `sources` 与演示素材 rel 交集可精确识别）→ 大脑索引 `POST /api/brain/index`（rebuild=false，第二轮：扫描 107/新增 20/跳过 87）→ 图谱 585 节点/1038 关系 → 问答冒烟「为什么选 LoRa」回答 525 字、带引用（首条 `decisions/smart-greenhouse-d2026-001-communication.md`）；③`cleanup_demo.py` 清理归零：后端在线前置 + 编译队列空闲守卫 → 4 素材 unlink → 17 条目经 `DELETE /api/knowledge` 三合一删除（文件 + index.md 重建 + brain.remove，逐条 `brain_removed=True`）→ 复核残留素材/条目均为 0；④素材/条目/索引.md 全部回到演示前状态。
>
> **偏差补记（2026-09-04，T-508）**：①**首验暴露两处脚本缺陷并已修复**——`/api/brain/index` 服务端内部超时 1800s（engine.py ainsert timeout）大于客户端 1500s 导致 socket `TimeoutError`（不经 URLError 包装）未捕获直接崩溃，客户端超时改 1900s 并在 `_http` 捕获 `TimeoutError`；`inbox.list_materials` 返回 Windows 反斜杠路径而条目 frontmatter `sources` 为 posix 格式，交集恒空导致清理「0 条目」，rel 统一 `as_posix()` 修复。修复后第二轮全链路 + 清理完整走通。②**graph 节点数不回落基线 337**：a) 演示触发的索引为 scope=all 全量扫描，顺带把 58 条历史未索引条目补入大脑（本应存在的数据，非演示产物）；b) LightRAG `adelete_by_doc_id` 删除文档 chunk 与独占实体，多文档共享/合并实体不删，清理后残留 7 个演示相关实体标签（D-2026-001/LoRa/NB-IoT 等），知识文件与条目已删净——共享实体残留属 LightRAG 合并机制预期行为，如需彻底归零可大脑重建（破坏性，不作为清理默认）。③materials 39 vs 基线 37：演示期间运行中的采集源正常捕获 2 条新素材（无 demo 标记，正确不清理）。④脚本「队列失败任务」提示为 queue 累计历史计数（21 条为 M4 以来积累），本轮 4 条演示素材全部编译成功。⑤首轮编译触发 9 条（含 5 条历史未编译素材）产出的历史条目属编译管线正常行为。

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
