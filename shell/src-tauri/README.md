# KnowSeq 桌面壳（Tauri 2，方案 A）

主窗加载本机控制台 `http://127.0.0.1:8765`（ADR-016 决策 1，FastAPI 后端零改动、
壳不打包 dist、不管理后端生命周期）。启动探测 `GET /api/status` 见 `src/main.rs`：
未就绪时显示内置提示页（`../fallback/index.html`）而非白屏，就绪后自动导航。

## 方案 B sidecar 口子（ADR-016 决策 4）

> 说明：`tauri.conf.json` 由 tauri-build 以严格 JSON 解析（**不支持 JSONC 注释**），
> 原 REQ-505 规划的「externalBin 注释位」无法以注释形式留在该文件内，
> 口子注释迁移至本文件与 `src/main.rs` 头注（偏差已补记 m5-requirements.md）。

迁移方案 B（壳内嵌 dist、Python 后端打包为 sidecar 子进程随壳启动）时的启用步骤：

1. `tauri.conf.json` 的 `bundle` 节增加：`"externalBin": ["binaries/knowseq-backend"]`
   （PyInstaller 产物置于 `src-tauri/binaries/`，文件名带 target triple 后缀）；
2. 放行 WebView Origin：`app/web/server.py` 本机访问限制中间件中
   `tauri.localhost` 视为本机（迁移注释见该文件校验处）；
3. 前端请求指向后端绝对地址：构建时设置 `VITE_API_BASE`
   （前缀位见 `webui/src/api.ts`）。

三处口子均指向 ADR-016 决策 4。
