---
title: "ADR-010: 交互层（FastAPI + 轻量自研前端）"
status: accepted
date: 2026-09-02
---

# ADR-010 交互层

## 背景

需要本地 Web 控制台：问答（带引用）、图谱浏览、采集控制、素材与知识管理、设置。要求**轻量自研**，但允许使用现成组件。

## 决策

- 后端：**FastAPI** 本地服务，提供 REST API（问答、图谱数据、采集开关、素材/知识 CRUD、设置）。
- 前端：轻量自研单页应用（Vue3 或纯 HTML+CDN，M4 定稿），复用现成组件：
  - 图谱可视化：**vis-network** 或 **ECharts graph**
  - 知识编辑：**CodeMirror**（可选）
- 页面：问答页 / 图谱页 / 采集控制 / 素材与知识管理 / 设置页。

## 备选方案与理由

- **直接复用 LightRAG WebUI**：改动小，但无法承载采集控制/管理/设置等自研能力 → 自研薄壳 + 复用其图谱/检索能力。
- **Electron/Tauri 桌面壳**：更重 → 浏览器访问本地 Web 更轻。

## 后果

- 需维护一套自研前端；图谱组件选型（vis-network vs ECharts）在 M4 定稿并更新 ADR。
- 浏览器访问 `http://127.0.0.1:<port>`，无需安装桌面框架。

## 关联

- 关联里程碑：M4
- 关联任务：T-011
- 相关 ADR：ADR-009（大脑层）、ADR-011（Windows 集成）
- 修订：ADR-015（前端部分——"Vue3 或纯 HTML+CDN"改为 React 19 + Vite + TS 并移植 llm_wiki 组件，图谱选型落定 sigma.js 系；FastAPI 后端与页面范围不变）
- 需求：FR-030、FR-031、FR-040、FR-041、FR-042
