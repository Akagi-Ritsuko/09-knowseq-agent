---
title: "ADR-003: 屏幕/音频采集用 screenpipe"
status: superseded（已被 ADR-014 取代）
date: 2026-09-02
superseded-by: ADR-014
---

# ADR-003 屏幕/音频采集

> **状态说明（2026-09-02）**：本决策已被 [ADR-014](ADR-014-vibevoice-asr.md) 取代 —— 会议音频采集改用 VibeVoice-ASR 本地离线转写；屏幕画面 OCR 采集移出 M1 范围。以下保留原文留痕。

## 背景

需要"自动无感"采集屏幕内容与系统音频/会议，且尽量本地化、支持 Windows。

## 决策

- 采用 **screenpipe**：本地常驻采集屏幕（无障碍 API 提取文本，OCR 兜底）+ 音频（Whisper 本地转写），数据存本地 SQLite，带搜索 API，支持 Windows。
- 屏幕/音频文本作为采集源之一写入 `inbox/`（对应 FR-001）。

## 备选方案与理由

- **自研轻量采集（剪贴板+前台窗口+OCR）**：更轻，但屏幕内容抓不全、无音频转写 → 作为兜底备选，不首选。
- **云录制（Rewind/Limitless 等）**：数据出本机，不符合本地优先 → 不选。

## 后果

- screenpipe 为 Rust 项目，安装相对较重；需在 M1 验证其在目标 Windows 机器上的运行稳定性。
- 音频转写能力同时覆盖"会议"采集场景（FR-001）。

## 关联

- 关联里程碑：M1
- 关联任务：T-002
- 相关 ADR：ADR-002（采集流水线）
- 需求：FR-001
