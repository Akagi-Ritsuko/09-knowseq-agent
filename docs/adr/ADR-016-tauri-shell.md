---
title: "ADR-016: 桌面壳采用 Tauri 2.x（方案 A：壳加载本机 URL）+ 桌面悬浮控件"
status: accepted
date: 2026-09-04
---

# ADR-016 桌面壳（Tauri 方案 A）与悬浮控件

## 背景

M4 交付后控制台形态为「FastAPI 托管 dist + 浏览器访问 `http://127.0.0.1:8765`」。用户提出桌面化诉求：

- 以独立桌面窗口使用控制台，不再手动开浏览器。
- 会议捕获需要一个**常驻桌面的透明开始/结束按钮**：始终置顶、可拖拽改变位置（控制对象为 ADR-017 的系统声音捕获）。
- ADR-010 曾以「更重」为由搁置 Electron/Tauri 桌面壳备选；上述需求（悬浮置顶控件、关窗后台常驻）超出纯浏览器形态能力，需重新评估。

调研 [Zackriya-Solutions/meetily](https://github.com/Zackriya-Solutions/meetily)（MIT）作为同类本地会议纪要应用参照：Tauri 2.x（Rust）+ Next.js，多窗口 + 托盘 + 防多实例；其音频捕获/转写在 Rust 侧（cpal loopback + whisper.cpp），与本项目的 Python 捕获 + asr_infer 转写路线不同。

## 决策

1. **桌面壳采用 Tauri 2.x，起步走「方案 A：壳加载本机 URL」**：
   - 主窗口 WebView 直接加载 `http://127.0.0.1:8765`（FastAPI 现役地址）。
   - **FastAPI 后端独立进程，零改动**：壳不打包 dist、不管理后端生命周期（后端仍由现有 run.py / 托盘负责）。
   - Origin 无障碍：WebView 的 Origin 即 `http://127.0.0.1:8765` 本身，server.py 现有 Host/Origin 本机校验直接放行，无需改动。
2. **悬浮控件用 Tauri 多窗口实现（配置级，无新依赖）**：
   - 独立小窗：`transparent: true` + `alwaysOnTop: true` + `decorations: false`，承载「开始 / 结束」两个会议采集按钮。
   - 拖拽：窗口拖拽区域 `data-tauri-drag-region`，按住空白处拖动改变位置。
   - 按钮动作调用 FastAPI 单源启停 API（T-408 已有 `/api/start|stop/{name}`），与托盘/控制台状态同源。
3. **壳与 pystray 托盘并存**：关主窗 = 隐藏到托盘（后端继续运行），彻底退出走托盘菜单；单实例防护参考 Meetily v0.4.0 关窗隐藏（#471）与防多实例（#476）配置思路。
4. **为「方案 B：sidecar 打包 Python 后端」预留三条演进口子（本次不实现）**：
   - ①前端 `webui/src/api.ts` 请求 base 预留 `import.meta.env.VITE_API_BASE` 前缀位（默认空串 = 现行为，A 方案不生效）。
   - ②server.py Host/Origin 校验处注释迁移说明：B 方案（壳内嵌 dist 经自定义协议访问）需放行 Tauri 自定义 Origin（`tauri.localhost`）；A 方案不改。
   - ③tauri.conf.json 预留 `externalBin`/sidecar 配置位注释，B 方案启用时把 Python 后端打包为 sidecar 子进程随壳启动。
5. **Meetily 定位为「思路与配置参考」，不整抄**：其 Rust 捕获/转写栈与既定路线冲突（见 ADR-017），仅参考会话模型、分段参数、托盘与单实例配置；引用标注 `Reference: Zackriya-Solutions/meetily (MIT)`。

## 备选方案与理由

- **方案 B：sidecar 打包 Python 后端（PyInstaller）**：分发单安装包、体验最佳，但打包重（依赖/模型体积）、构建与调试复杂 → 作为**演进目标**保留（口子已留），非起步。
- **Electron**：Chromium 全量打包，体积/内存显著大于 Tauri → 不选。
- **维持纯浏览器访问**：最轻，但无法承载悬浮置顶控件与关窗后台常驻体验 → 保留为无壳环境的后备形态（后端零改动天然支持）。
- **整抄 Meetily（连 Rust 捕获/转写一起移植）**：Rust 栈与 ADR-014 既定 asr_infer 路线冲突，重写成本高且推翻已验收链路 → 只抄思路与配置。

## 后果

- **新增前置依赖：Rust 工具链**（rustup + MSVC Build Tools）。本机当前未安装 cargo/rustc，M5 壳工程启动前须先就位（T-502 前置）。
- 后端零改动；前端仅 api.ts 前缀位预留（行为不变）。开发态仍可纯浏览器访问，A 方案壳与浏览器形态等价。
- 采集入口三个（托盘 / 控制台 / 悬浮按钮），状态同源（FastAPI API）。
- 方案 A 下壳与后端为两个进程，需先后端后开壳（壳启动时检测后端未就绪则提示）；B 方案演进后可消除该步骤。

## 关联

- 修订：ADR-010（交付形态——在「浏览器访问本地 Web」基础上新增 Tauri 桌面壳承载形态，FastAPI 后端与页面范围不变；原"Electron/Tauri 更重"备选结论按新需求更新）
- 关联里程碑：M5
- 关联任务：T-012 / T-502（壳骨架）/ T-503（桌面体验）/ T-504（悬浮控件）/ T-505（sidecar 口子）
- 相关 ADR：ADR-010（前端/交付形态）、ADR-011（Windows 集成）、ADR-017（系统声音捕获，悬浮控件控制对象）
- 需求：REQ-502、REQ-503、REQ-504、REQ-505
- 参考：[Zackriya-Solutions/meetily](https://github.com/Zackriya-Solutions/meetily)（MIT）、[Tauri 2.x](https://tauri.app/)
