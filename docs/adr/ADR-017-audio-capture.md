---
title: "ADR-017: 会议系统声音捕获采用 WASAPI loopback 直采（pyaudiowpatch），复用 asr_infer 转写"
status: accepted
date: 2026-09-04
---

# ADR-017 系统声音捕获（WASAPI loopback 直采）

## 背景

ADR-014 落地后，meeting 源现状是**离线路径**：音频文件拖入 drop 热文件夹 → asr_infer 子进程转写 → `inbox/meeting/`。真实会议场景（腾讯会议等）下系统播放的声音（对方发言）并没有被捕获——经代码核查（`app/capture/meeting_source.py`），无 loopback/麦克风采集实现。

用户需求：会议进行时直接拿到系统声音转写入库，配合桌面悬浮开始/结束按钮（ADR-016）。

调研 Meetily（MIT）实现：音频捕获在 Rust 侧（cpal 抓 loopback + 麦克风可选混音 → 分段 wav + 静音检测），转写也在 Rust（whisper.cpp/Parakeet）。

## 决策

1. **捕获路线：WASAPI loopback 直采（Python 侧）**——新增 `app/capture/system_audio_source.py`，用 **pyaudiowpatch** 抓默认输出设备（扬声器）的 loopback 混音 → 定长分段落 wav（默认 5 分钟/段，静音检测切分参数参考 Meetily）→ 交给转写链路。
2. **转写链路完全复用 ADR-014**：分段 wav 走与 drop 热文件夹相同的 asr_infer 子进程调用（VibeVoice-ASR-BitNet）→ `write_material(source=meeting)` → `inbox/meeting/`；素材 meta 加来源标记 `system-audio`，与拖文件路径区分。
3. **麦克风混音可选，默认关**：pyaudiowpatch 亦可抓麦克风，与 loopback 混为单 wav。注意 **loopback 只含扬声器输出**（不含自己麦克风的声音）；要收录自己发言需开启 mic 混音（config `sources.system_audio.include_mic`，默认 false）。
4. **本 ADR 为 ADR-014 的扩展**：转写引擎、drop 热文件夹、调用参数（`-t 4` 等）均不变；只新增「捕获源」，不动转写链路。
5. 悬浮按钮（ADR-016）控制该源启停：开始 = start `system_audio` 源，结束 = stop + 收尾转写最后一段（不足分段时长也立即落盘转写）。

## 备选方案与理由

- **Meetily 式 Rust 侧捕获（cpal）**：延迟与性能更优，但引入 Rust 开发栈与构建负担，且其转写（whisper.cpp）与既定 asr_infer 路线冲突 → 只参考其分段/静音检测参数与坑位记录（如蓝牙耳机回连 BLUETOOTH_PLAYBACK_NOTICE）。
- **screenpipe（ADR-003，已被 ADR-014 取代）**：外部 Rust 引擎常驻、无 Python 库形态 → 不选（结论不变）。
- **会议软件 SDK（腾讯会议等）**：接入门槛高、绑定特定软件、无通用性 → 不做。
- **虚拟声卡方案（VB-Cable 等手动路由）**：需用户手动配置系统声音路由，体验差 → 不选。

## 约束与代价

- pyaudiowpatch 仅 Windows（WASAPI loopback 本为 Windows 特性），符合项目 Windows 优先定位。
- loopback 抓的是整机输出混音：系统提示音/媒体播放也会进入音频，转写噪音增加——靠静音检测与分段缓解，**中文会议实时转写质量以实测为准**（承接 ADR-014 精度约束）。
- 实时性：分段落盘后依序转写（近实时，非逐句实时）；长会议产生多段 wav，转写耗时受 CPU 性能约束（RTF 0.71 口径）。
- 蓝牙耳机场景：系统切换输出设备后 loopback 设备随之变化，需监听默认设备切换并重建捕获流（Meetily 有同类坑记录）。

## 关联

- 扩展：ADR-014（会议音频采集——新增系统声音捕获源；转写引擎与 drop 热文件夹路径不变）
- 关联里程碑：M5
- 关联任务：T-012 / T-501（捕获源）/ T-504（悬浮控件控制）/ T-509（端到端验收）
- 相关 ADR：ADR-014（转写链路）、ADR-016（悬浮控件）、ADR-002（采集流水线）
- 需求：REQ-501
- 参考：[Zackriya-Solutions/meetily](https://github.com/Zackriya-Solutions/meetily)（MIT）、[PyAudioWPatch](https://github.com/s0d3s/PyAudioWPatch)
