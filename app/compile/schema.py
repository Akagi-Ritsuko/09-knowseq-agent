"""知识库条目 schema 与定位常量（T-207 REQ-207）。

Ported from nashsu/llm_wiki (GPL-3.0) —— 原 schema.md / purpose.md 文件
改为内置常量（P4 决策）：不读外部文件，prompt 直接拼接。

九类 → 五类裁剪（ADR-008）：decision / lesson / concept / connection / query。
query 型条目（疑问/待研究）frontmatter 另有 status: open/resolved，
用于 REQ-209 断链自动建 stub 与 REQ-210 review 闭环。
"""

CATEGORIES = ("decisions", "lessons", "concepts", "connections", "queries")

CATEGORY_BY_TYPE = {
    "decision": "decisions",
    "lesson": "lessons",
    "concept": "concepts",
    "connection": "connections",
    "query": "queries",
}

SCHEMA = """# 知识库 Schema（AUTHORITATIVE——页面类型与目录路由的唯一依据）

所有条目写入 knowledge/ 目录，按 frontmatter `type` 路由到对应子目录：

| type | 目录 | 定义 |
|------|------|------|
| decision | knowledge/decisions/ | 做出的选择、取舍与理由（含被否决的备选方案）。面向"我们为什么这样做" |
| lesson | knowledge/lessons/ | 踩坑、教训、修复记录与经验总结。面向"什么情况下会再犯、如何避免" |
| concept | knowledge/concepts/ | 概念、原理、方法论、技术机制的解释。面向"它是什么、如何运作" |
| connection | knowledge/connections/ | 跨条目/跨主题的关联与对比（A 与 B 的异同、因果、演进关系） |
| query | knowledge/queries/ | 未解决的疑问、待研究问题。frontmatter 必须含 `status: open`（已解决改 `resolved` 并补结论） |

路由规则：
- 每个条目的 frontmatter `type` 必须与其 FILE 路径中的目录一致（type: concept → knowledge/concepts/）。
- 一个素材通常产出多个条目；拿不准类型时优先 concept；明确是"选择+理由"才用 decision。
- query 条目用于记录素材中悬而未决的问题，不要把已解决的问题伪装成 query。

所有条目 frontmatter 统一字段（严格 YAML，首行必须是 `---`）：
- type     — 上表五种之一
- title    — 条目标题（含冒号需加引号）
- created  — YYYY-MM-DD
- updated  — YYYY-MM-DD
- tags     — 行内数组 `[a, b]`
- related  — 行内数组，只写条目 slug（不带 knowledge/、不带 .md、不带 [[ ]]）
- sources  — 行内数组，必须包含来源文件名
- （仅 query）status — open 或 resolved"""

PURPOSE = """# 知识库定位

这是个人知识库，由采集层收到的素材（会议记录、剪贴板、网页、文件、
IM 消息）经 LLM 编译而成。目标是：把一次性输入沉淀为可检索、可交叉
引用的结构化知识。

编译准则：
- 忠实于素材：不编造素材中不存在的事实、结论或记录；来源必须在
  frontmatter sources 中可追溯。
- 保留结构化数据原文：SQL DDL、API 签名、配置、表格等逐字保留在
  代码块或 Markdown 表格中，不得降级为散文转述。
- 区分主体归属：素材提到多个实体/模型/方法时，断言、评测、局限
  不得跨主体转移或泛化合并。
- 关联优先：与库中既有条目相关时用 [[wikilink]] 交叉引用。"""
