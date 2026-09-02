---
title: "ADR-013: inbox 素材模型与存储规范"
status: accepted
date: 2026-09-02
---

# ADR-013 inbox 素材模型与存储规范

## 背景

ADR-002 定了"统一写入 `inbox/`、只追加不修改"，但未定义具体存储形态。M1 各采集源需要一致的素材格式、去重与可溯源能力。

## 决策

- 目录：`inbox/<source>/`，source ∈ {screen, clipboard, feishu, file, web, manual}。
- 素材：单个 `.md` 文件，文件名 `<source>_<yyyyMMdd_HHmmss>_<短id>.md`；内容为 YAML frontmatter + 正文。
- frontmatter 字段：`id`、`source`、`captured_at`（ISO 8601）、`meta`（来源标识：URL/会话/原文件路径/等）、`compiled: false`（M2 消费的幂等标记）。
- 去重：clipboard/web/manual 用内容哈希（指纹存 `inbox/.dedup.json`）；screen/feishu/file 按事件/文件天然去重。
- 统一入口：`app/capture/inbox.py` 提供 `write_material(source, title, content, meta)`，所有采集源只通过它写入。

## 备选方案与理由

- **JSONL 单文件**：追加高效，但无法直接用 Obsidian/编辑器打开、难人工审阅 → 选"单 md 文件"。
- **数据库（SQLite）为主存储**：查询强，但违背"纯文本可读/可恢复"取向 → 仅把 `.dedup.json` 等轻量索引放文件。

## 后果

- 素材可被 Obsidian 直接打开、可人工审阅（符合 NFR-005 可审计、NFR-006 可恢复）。
- M2 编译层按 `compiled: false` 消费；新来源扩展只需新增子目录与 meta 约定。

## 关联

- 关联里程碑：M1
- 关联需求：FR-001~006
- 相关 ADR：ADR-002（采集流水线）
- 关联任务：T-102
