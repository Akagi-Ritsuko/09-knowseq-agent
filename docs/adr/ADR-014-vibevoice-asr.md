---
title: "ADR-014: 会议音频采集用 VibeVoice-ASR-BitNet（取代 ADR-003 screenpipe）"
status: accepted
date: 2026-09-02
supersedes: ADR-003
---

# ADR-014 会议音频采集

## 背景

ADR-003 曾决定用 screenpipe 采集"屏幕内容 + 系统音频"。落地调研发现：

- screenpipe 为 Rust 项目，官方以桌面应用/CLI 分发，**无可 import 的 Python 库**，集成只能靠本地 HTTP API（127.0.0.1:3030）拉取，需常驻第三方引擎。
- 调研微软开源 **VibeVoice** 语音家族（MIT）：
  - **VibeVoice-ASR-7B**（HF Transformers 版）：60 分钟单遍转写、Who/When/What 结构化输出，但 fp16 需 14~18GB 显存，24GB 卡实测约 30 分钟音频为上限 —— 门槛高。
  - **VibeVoice-ASR-BitNet**（2026-07-23 发布）：面向边缘 CPU 的压缩版，异构量化（VAE 用 I8_S、LM 用 BitNet 三值 I2_S），解码器从 Qwen2.5-7B 换成 1.5B，模型 **4.62GB → 1.58GB**，官方推理引擎 **VibeASR.cpp**（ggml 框架，MIT）在 4 线程 CPU 上即可实时（i7-13700 Windows 实测 RTF 0.71），比 Whisper.cpp 同尺寸快 1.6~2.3×，**无需 GPU**。

## 决策

- 会议/通话音频采集采用 **VibeVoice-ASR-BitNet 本地离线转写**：音频文件（会议/通话录音）→ 子进程调用 VibeASR.cpp 的 `asr_infer` CLI → 转写结果组装为 Markdown → `write_material(source=meeting)` → `inbox/meeting/`。
- 集成形态：**本地引擎 + 子进程调用**（类似 whisper.cpp 模式）。引擎与 gguf 模型（约 1.6GB）作为可选组件单独准备，不进 Python 主依赖；引擎未就绪时源状态 error，不影响其他源。
- inbox 源集合由 `screen` 改为 `meeting`（`sources.screen.*` → `sources.meeting.*`）。
- **屏幕画面文字（OCR）采集移出 M1 范围**：VibeVoice 是语音模型，不覆盖屏幕 OCR（用户已确认舍弃屏幕转写）；如后续需要，再评估 screenpipe 或其他方案。
- TTS 能力（VibeVoice-TTS-1.5B / Realtime-0.5B）与本决策无关，M4/M5 播报场景届时再评估（注意官方仓库已移除 TTS 代码，仅存 HF 权重）。

## 约束与代价（实测/官方口径）

- 精度：较 7B FP16 版 WER 绝对值退化 1~4 个百分点；中文会议场景偏高（AISHELL4 27.45、AliMeeting 40.58），远场/口音会进一步退化 —— **中文会议录音的转写质量以实测为准**。
- 说话人/时间戳：7B 版原生输出 Who/When/What；BitNet 用 1.5B 解码器，输出为 JSON 转写，**是否保留 Speaker/Timestamps 字段待实测确认**（见 T-113）。
- Windows 构建门槛：VibeASR.cpp **仅支持 GCC/Clang（推荐 MinGW-w64），不支持 MSVC**；需 CMake 构建 + 从 HF 下载预量化 gguf 模型。
- 长音频：单遍处理时长上限受内存约束（1.5B 解码器远低于 7B），超长录音仍需分片与后处理。
- 官方声明"仅供研发用途，未充分测试前不建议商业使用"。

## 备选方案与理由

- **VibeVoice-ASR-7B（HF Transformers，GPU）**：精度最好（Who/When/What 原生输出），但 24GB 显存仅能跑约 30 分钟音频，依赖 torch/transformers 重栈 → 作为有 GPU 机器的**精度升级备选**保留，非主方案。
- **继续用 screenpipe**：屏幕+音频一把抓，但 Rust 引擎重、常驻后台、无 Python 库形态 → 不选（屏幕转写已舍弃）。
- **云端 ASR API（Whisper API / 火山等）**：省资源，但音频出本机，违反 NFR-001 本地优先 → 不选。

## 后果

- REQ-104 / T-002 / T-104 按本方案重写；现有 `screenpipe_source.py`（外部 API 拉取实现）待重写为 meeting 转写源（子进程调用 `asr_infer`）。
- T-113（说话人溯源）取决于 BitNet 输出 schema：若含 Speaker/Timestamps 直接落 meta；若不含，则 meeting 源暂为纯转写，说话人溯源待 7B GPU 版或后处理方案。
- 落地前置：本机安装 MinGW-w64 并构建 VibeASR.cpp（或采用官方后续发布的预编译产物），下载 `microsoft/VibeVoice-ASR-BitNet` 模型。

## 关联

- 取代：ADR-003（screenpipe）
- 关联里程碑：M1
- 关联任务：T-002 / T-104 / T-113
- 相关 ADR：ADR-002（采集流水线）、ADR-013（inbox 素材模型）
- 修订：ADR-017（会议音频捕获源扩展——新增 WASAPI loopback 系统声音直采（pyaudiowpatch）分段 wav，复用本 ADR 的 asr_infer 转写链路与 drop 热文件夹路径；转写引擎不变）
- 需求：FR-001
- 参考：[VibeASR.cpp](https://github.com/microsoft/VibeASR.cpp)、[模型 HF](https://huggingface.co/microsoft/VibeVoice-ASR-BitNet)、[技术报告](https://arxiv.org/abs/2607.21075)
