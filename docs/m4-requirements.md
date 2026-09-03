# M4 交互层需求拆分（REQ-401 ~ REQ-411）

> 日期：2026-09-03　|　对应里程碑：M4　|　覆盖规划级任务：T-011 / T-115
> 依据：ADR-010（2026-09-02 修订版）、ADR-015（llm_wiki 移植）、PRD FR-030/031/040~042、architecture.md、milestones.md M4 验收标准
> 上游依赖：M3 大脑层（REQ-301~306）已关闭——brain API 5 端点与 graph JSON 就绪；M2 编译层 compile API 8 端点就绪

---

## §0 范围与前置决策

### 0.1 目标

控制台 React 化升级：React 19 + Vite + TS 新前端完整承载既有 `app/web/static/` 全部页面能力，并新增问答（带引用溯源）、知识库浏览（wikilink/frontmatter）、图谱可视化（sigma.js）三类 M4 核心体验，达成里程碑验收闭环——**提问 → 带引用回答 → 跳转来源 → 查看图谱**。FastAPI 后端不变（仅按需补齐管理 API，无破坏性变更）。

### 0.2 前置决策（本里程碑固化）

| # | 决策 |
|---|------|
| D1 | **技术栈（ADR-010 修订版）**：React 19 + Vite + TypeScript；FastAPI 后端不变，既有 API 契约不破坏 |
| D2 | **工程形态与托管**：前端源码 `webui/`（仓库根，git 跟踪）；`npm run build` 产物输出 `app/web/dist`（git 跟踪，运行时无需 Node）；FastAPI **dist 优先、旧 static 兜底**（REQ-411 验收通过后删除旧 static 页面）；开发态 `vite dev` 将 `/api` 代理到 FastAPI（127.0.0.1:8765） |
| D3 | **图谱技术栈**：sigma.js v3 + @react-sigma/core + graphology + graphology-layout-forceatlas2 + graphology-communities-louvain（ADR-010 修订版/ADR-015 落定，弃 vis-network）。M3 D5"vis-network 兼容 JSON"表述按此修订——`{nodes, edges}` JSON 结构不变，由前端转换为 graphology Graph |
| D4 | **设计系统先行**：任何页面开发前必须调用 taste-skill 系列 skill（design-taste-frontend v2 为主力，可配合 minimalist-ui / high-end-visual-design 定视觉方向）——先读需求推断设计语言，定三档 dial（VARIANCE/MOTION/DENSITY；本地工具型控制台：中等密度、克制动效），产出统一设计系统（布局/字体/色板/间距/组件样式）；全部页面共享同一设计系统，禁止每页各写一套；全程遵循 anti-slop 规则；产出物若截断改用 full-output-enforcement。**T-402 落定结论**：dark tech 工具风单主题锁定（不做双主题）；三档 dial `VARIANCE 3 / MOTION 3 / DENSITY 6`（工具型控制台需可预测布局 + 克制动效 + 中等密度）；唯一 accent 绿 `#3ecf8e`（避开 AI 紫蓝，ok 状态同族复用），状态色 warn/err 独立；系统字体栈 + mono 数据字体（本地离线工具不引 web font）；圆角两档（控件 6px / 面板 10px）；落地为 `webui/src/styles/` 三文件（tokens.css / base.css / components.css），自建 CSS 变量不引重型组件库（design-taste-frontend 明确 dashboard 类在其 landing-page 范围外，anti-slop 原则与 dial 机制照常执行） |
| D5 | **移植合规（ADR-015）**：移植 llm_wiki 组件（wiki-reader/frontmatter-panel/graph-view/graph-layout-worker 等）的文件头部注明 `Ported from nashsu/llm_wiki (GPL-3.0)`；`reference/` 不进仓库不分发 |
| D6 | **后端补齐（无破坏性）**：素材状态/标记/预览 API、知识条目 PUT/DELETE（含大脑索引一致性 `brain.remove`）、settings 扩展（`brain` 节、`llm_api_key` 只写不回读）——均为新增端点或字段扩展，既有端点行为不变 |
| D7 | **安全沿用**：M1 Host/Origin 本机校验中间件原样生效于新前端全部路由（含 SPA fallback 与静态资源） |
| D8 | **路由规划**：`/ask` 问答、`/graph` 图谱、`/knowledge` 知识库、`/compile` 编译、`/materials` 素材、`/capture` 采集控制、`/settings` 设置；全局布局侧边导航；旧页面"采集状态/手动导入"能力归采集控制页与全局状态条，"大脑面板"能力归问答页（问答/检索）+ 图谱页（图谱/索引）+ 全局状态条（状态/索引触发） |

### 0.3 不在 M4 范围（裁剪）

- T-116 Chrome MV3 剪藏插件（M4 后延伸，另行启动）
- T-106/T-004 飞书联调（凭据就绪后补做，M1 遗留）；T-113 说话人/时间戳
- M5（Windows 集成完善/演示打磨）
- LightRAG Server/WebUI、图谱手动编辑（增删实体/边）、多用户/鉴权（保持本机单用户）
- 移动端适配、国际化

### 0.4 与现有约定对齐

- 环境：Node v22.9.0 LTS + npm 11 已确认
- API 风格：对齐既有端点——`_require_brain` 404 兜底、LLM 未配置 400 细节提示、路径参数防穿越（resolve 后必须落在 knowledge/inbox 子树内）
- 旧页面能力基线（全部须覆盖，验收前不删）：采集状态/手动导入/网页抓取/飞书导入/素材列表/编译状态/编译触发/Review/知识库浏览/手动工具 lint-dedup-enrich/大脑面板/设置

---

## §1 REQ-401 前端工程骨架与静态托管（T-401）

| 项 | 内容 |
|----|------|
| 描述 | 新建 `webui/` Vite + React 19 + TS 工程；FastAPI 改造为 dist 优先/static 兜底；七页路由骨架 |
| 接口 | `webui/package.json`（react/react-dom/react-router-dom）；`vite.config.ts`：`server.proxy['/api'] → http://127.0.0.1:8765`、`build.outDir → ../app/web/dist`；server.py：`/` 与未知非 `/api` 路径优先返回 `dist/index.html`（SPA fallback），dist 不存在时回退旧 static；`/static` 挂载保留 |
| 适配点 | 不动 local_only 中间件与既有 API；路由骨架（AppShell + 七页占位）先行，内容由后续 REQ 填充 |
| 验收 | `npm run build` 后 FastAPI 托管新前端可访问（七页可导航）；`vite dev` 下 `/api` 代理连通；恶意 Host/Origin 仍 403（不回退）；旧 static 页面在验收期仍可访问 |

## §2 REQ-402 统一设计系统（T-402）

| 项 | 内容 |
|----|------|
| 描述 | 调用 taste-skill（design-taste-frontend v2 主力）产出设计系统，作为全部页面的唯一视觉来源 |
| 接口 | 设计系统产出：design tokens（色板/字体/字号/间距/圆角/阴影/动效时长）+ 基础组件样式（按钮/输入/卡片/表格/标签/空态/加载态/确认弹窗/Toast/侧边导航）+ dial 记录（VARIANCE/MOTION/DENSITY 结论与理由） |
| 适配点 | 本地工具型控制台定位：信息密度中等、动效克制、无营销式装饰；Markdown 渲染与代码块样式纳入 tokens；tokens 以 CSS 变量 + 共享组件落地（单一 `styles/` 源） |
| 验收 | 全部页面消费同一 tokens（无页面级私有配色/间距）；三档 dial 有明确记录；对照 anti-slop 规则无模板化 AI 风 UI；后续页面评审以设计系统为基线 |

## §3 REQ-403 全局布局与状态总览（T-403）

| 项 | 内容 |
|----|------|
| 描述 | 应用外壳：侧边导航七页 + 全局状态条（采集/编译/大脑三态聚合） |
| 接口 | `GET /api/status`（采集源状态聚合）、`GET /api/compile/status`、`GET /api/brain/status` 轮询汇总；导航高亮当前路由；大脑索引触发（增量/重建）入口置于状态条 |
| 适配点 | 覆盖旧"采集状态"卡片与"大脑面板"状态区能力；`/` 重定向 `/ask`；未知路由兜底页 |
| 验收 | 七页可导航、当前页高亮；状态条真实反映三类状态（源运行中/LLM 就绪/大脑就绪）；索引触发按钮可用且状态刷新 |

## §4 REQ-404 编译页（T-404）

| 项 | 内容 |
|----|------|
| 描述 | 编译状态/触发/Review 待处理/手动工具四区（覆盖旧编译页全部能力） |
| 接口 | `GET /api/compile/status`、`POST /api/compile/trigger`（`{scope:"all"\|"path", path?}`）、`GET /api/compile/reviews`、`POST /api/compile/reviews/resolve`、`POST /api/compile/lint` / `dedup` / `enrich`（`?dry_run=`） |
| 适配点 | 对齐既有 API 契约，仅做展示与交互升级（队列计数/限流暂停/warnings/last_error 可读化；Review 解决带备注；手动工具结果结构化展示而非纯文本 pre） |
| 验收 | 触发全部/单路径入队并反映 pending；Review 加入-解决闭环；lint/dedup/enrich-dry 结果可读展示；与旧页面能力一一对应（不回退） |

## §5 REQ-405 问答页 FR-030（T-405）

| 项 | 内容 |
|----|------|
| 描述 | 自然语言提问 → 带引用回答，引用可点击跳转来源（knowledge 条目原文/素材） |
| 接口 | `POST /api/brain/query`（`{query, mode?, top_k?}`）、`GET /api/brain/search?q=&top_k=`（独立检索标签页）；未就绪 400 展示引导提示 |
| 适配点 | 引用映射：contexts.file_path 为 knowledge 相对路径 → 跳 `/knowledge?path=...`（条目详情）；条目 frontmatter sources 指向 inbox 素材 → 详情页内再跳素材预览；mode 切换（hybrid/local/global/naive/mix）；对话历史本地内存保持（不落库） |
| 验收 | 提问返回基于知识库的回答与引用列表；点击引用跳转条目详情可见原文；mode 可切换；brain 未就绪/未配置给出可操作提示（不白屏） |

## §6 REQ-406 知识库浏览页（T-406）

| 项 | 内容 |
|----|------|
| 描述 | 五类条目列表 + 条目详情（Markdown 渲染、[[wikilink]] 可点击跳转、YAML frontmatter 展示）+ index.md/log.md 视图（移植 llm_wiki wiki-reader/frontmatter-panel 模式） |
| 接口 | `GET /api/knowledge`（五类列表）、`GET /api/knowledge?path=`（单条全文，含 index.md/log.md——均在 knowledge 子树内）；wikilink 解析：条目列表建立 slug→路径索引，`[[target]]`/`[[target\|alias]]`/锚点归一后路由跳转 |
| 适配点 | 移植文件头注 `Ported from nashsu/llm_wiki (GPL-3.0)`；Markdown 渲染含表格/代码块/引用样式（对齐设计系统）；frontmatter 面板展示 type/date/tags/sources/related 等字段，sources 为素材链接可跳素材页 |
| 验收 | 五类分组列表与搜索过滤可用；详情页 Markdown 正常渲染、wikilink 点击跳转对应条目、断链 wikilink 有可辨识样式；index.md/log.md 可查看 |

## §7 REQ-407 图谱页 FR-031（T-407）

| 项 | 内容 |
|----|------|
| 描述 | brain graph JSON → graphology Graph → sigma.js v3 渲染；缩放/拖拽/点击节点高亮与详情面板（移植 llm_wiki graph-view + graph-layout-worker） |
| 接口 | `GET /api/brain/graph` → `{nodes:[{id,label,type}], edges:[{source,target,relation}]}`；转换：nodes 加点、edges 加边；布局 ForceAtlas2（Web Worker，节点阈值 220 分档迭代，inferSettings+assign），渲染循环 camera 缩放/拖拽 |
| 适配点 | 移植要点：nodeReducer/edgeReducer 高亮（点击聚焦 1.5x 邻居、其余 dimmed）、ZoomControls、布局迭代分档（140/90/65/40/28）、graphThemePalette 对齐设计系统；增强项：Louvain 社区着色（graphology-communities-louvain）、type 筛选、搜索定位；详情面板：label/type/度数/关连边（LightRAG 节点 id 为实体名，不对应 knowledge 文件路径，不做条目跳转） |
| 验收 | 真实图谱（31+ 节点）渲染流畅、布局收敛；缩放/拖拽/点击高亮与详情面板可用；空图/未就绪有提示；增强项（社区着色/筛选/搜索）至少社区着色完成 |

## §8 REQ-408 素材管理与采集控制页 FR-040（T-408）

| 项 | 内容 |
|----|------|
| 描述 | 素材列表（待提炼/已提炼状态、标记、预览）+ 采集控制页（各源启停、手动导入、网页抓取、飞书导入） |
| 接口 | 后端补齐：`GET /api/materials` 扩展返回 `compiled` 状态（list_materials 读 frontmatter）、`POST /api/materials/mark`（`{path, compiled}` 回写 frontmatter）、`GET /api/materials/content?path=`（预览，防穿越校验同 knowledge）；前端用既有 `POST /api/start\|stop`、`POST /api/import`、`POST /api/import/file`、`POST /api/web/ingest`、`POST /api/feishu/doc` |
| 适配点 | inbox.list_materials 扩展字段（读 frontmatter compiled/meta，保持既有字段不变）；素材页状态徽标（待提炼/已提炼）+ 标记切换 + 正文预览抽屉；采集控制页每源开关即时反映状态，meeting 源展示引擎就绪状态 |
| 验收 | 素材列表显示待提炼/已提炼；标记后 frontmatter 回写成功且状态即时更新（待提炼素材可标记已提炼/反向撤销）；素材预览可读；各源启停开关生效；手动导入/网页抓取可用 |

## §9 REQ-409 知识管理页 FR-041（T-409）

| 项 | 内容 |
|----|------|
| 描述 | 知识条目查看/编辑（写回 knowledge/ 文件）、删除需确认，并同步处理大脑层索引一致性 |
| 接口 | 后端补齐：`PUT /api/knowledge`（`{path, content}` 写回，resolve 防穿越）、`DELETE /api/knowledge?path=`（删文件 + `update_index` 重建 index.md + `brain.remove(rel_path)`——LightRAG `adelete_by_doc_id` + 本地 `index_state.json` 清理）；前端：知识库详情页编辑模式（源码编辑 + 保存确认）、删除确认弹窗（显示条目名与后果） |
| 适配点 | brain 引擎新增 `remove(doc_id)` 同步包装；删除条目若被其他条目 wikilink 引用，lint 可后续检出（不自动改写，行为与 M2 一致）；编辑保存后提示"重新索引后问答/图谱生效"（或触发增量索引按钮） |
| 验收 | 编辑保存后文件更新、详情页显示新内容、再次索引后问答反映新内容；删除需确认，删除后列表移除、index.md 同步、大脑图谱/检索不再含该条目（索引一致性）；防穿越（越界 path 404） |

## §10 REQ-410 设置页 FR-042（T-410）

| 项 | 内容 |
|----|------|
| 描述 | LLM API（base_url/model/Key）、embedding、监听目录、采集开关、编译与大脑配置节，保存持久化 config 重启生效 |
| 接口 | 扩展 `GET/POST /api/settings`：新增 `brain` 节（enabled/embedding.base_url/embedding.model/llm.base_url/llm.model）与 `llm_api_key`（POST 写入 .env `LLM_API_KEY`，GET 恒不回读、仅返回已设置标志）；既有 web/paths/compile/sources 节沿用 |
| 适配点 | 设置页分组表单（对齐 config 结构）：LLM API / Embedding / 监听目录（paths）/ 采集开关（sources）/ 编译（compile）/ 大脑（brain）/ Web；保存后提示"重启后生效"（进程内热更仅限既有已支持项）；Key 输入框回显占位符而非明文 |
| 验收 | 修改 base_url/model 保存 → config.yaml 落盘 → 重启服务后读取生效；Key 保存写入 .env 且 GET 响应不含明文；监听目录/采集开关/编译与大脑配置保存生效；非法值有校验提示 |

## §11 REQ-411 端到端验收与旧前端下线（T-411）

| 项 | 内容 |
|----|------|
| 描述 | 真实环境验收 M4 里程碑闭环；能力覆盖不回退核查；旧 static 前端下线；收尾文档同步 |
| 接口 | 验收脚本/走查清单：浏览器打开 `http://127.0.0.1:<port>` 完成「提问 → 带引用回答 → 跳转来源 → 查看图谱」闭环；采集开关/素材标记/知识编辑与删除（带确认）/设置持久化重启生效全部可用；编译链路与大脑面板功能不回退 |
| 适配点 | 下线 = 删除 `app/web/static/` 旧页面（server.py 保留 dist 托管 + SPA fallback）；changelog/tasks/milestones 留痕，T-011/T-115 标 done |
| 验收 | 里程碑 M4 验收标准全项通过；旧页面能力清单逐项在新前端核对无缺失；旧 static 删除后服务正常、无死链；文档全部同步一致 |

---

## §12 依赖与构建配置枚举（webui/）

```jsonc
// webui/package.json 关键依赖（T-407 完成后与实际安装对齐）
{
  "dependencies": {
    "react": "^19",
    "react-dom": "^19",
    "react-router-dom": "^7.6",
    "marked": "^18",
    "sigma": "^3.0.3",
    "@react-sigma/core": "^5.0.6",
    "graphology": "^0.26.0",
    "graphology-layout-forceatlas2": "^0.10.1",
    "graphology-communities-louvain": "^2.0.2"
  },
  "devDependencies": { "vite": "^6.3.5", "typescript": "~5.8.3", "@vitejs/plugin-react": "^4.5.0" }
}
```

> 版本偏差说明：@react-sigma/core 实际取 v5（规划写 ^4，v5 为当前稳定版且适配 React 19）；vite 取 6（Node 22.9.0 不满足 Vite 7 引擎要求 ≥22.12，见 T-401）；marked 实际 ^18。

```ts
// webui/vite.config.ts 要点
export default defineConfig({
  plugins: [react()],
  server: { proxy: { '/api': 'http://127.0.0.1:8765' } },
  build: { outDir: '../app/web/dist', emptyOutDir: true },
});
```

## §13 整体验收（对应 FR-030/031/040~042 与里程碑 M4 验收）

- **核心闭环**：提问 → 带引用回答 → 点击引用跳转来源（条目原文/素材）→ 查看图谱，全程在新前端完成
- **交互完整**：图谱缩放/拖拽/点击高亮与详情；wikilink 跳转；素材标记；知识编辑（写回）/删除（确认 + 大脑索引一致）；设置持久化重启生效
- **能力不回退**：旧 static 页面能力清单逐项覆盖（采集状态/导入/素材/编译/Review/手动工具/大脑面板/设置）
- **后端稳定**：FastAPI 无破坏性变更，既有 API 行为不变（新增端点/字段除外）
- **设计一致**：全站统一设计系统，无模板化 AI 风 UI
- 文档同步：changelog/tasks/milestones 留痕，T-011/T-115 done

## §14 待办映射

| REQ | 任务 | 覆盖规划级 |
|---|---|---|
| REQ-401 | T-401 | T-011/T-115 |
| REQ-402 | T-402 | T-011 |
| REQ-403 | T-403 | T-011 |
| REQ-404 | T-404 | T-011 |
| REQ-405 | T-405 | T-011/T-115 |
| REQ-406 | T-406 | T-011/T-115 |
| REQ-407 | T-407 | T-011/T-115 |
| REQ-408 | T-408 | T-011 |
| REQ-409 | T-409 | T-011 |
| REQ-410 | T-410 | T-011 |
| §13 验收 + 下线 | T-411 | M4 收尾 |
