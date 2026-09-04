# KnowSeq 全链路演示（T-508 / REQ-508）

从零跑通 **采集 → 编译 → 索引 → 问答 / 图谱** 的可重复演示路径，演示产物带统一标记、可一键清理，不污染真实数据。

## 目录

```
scripts/demo/
├── README.md          本文件
├── run_demo.py        演示主脚本
├── cleanup_demo.py    清理模式（回到演示前状态）
└── seed/              种子数据（4 份示例素材，主题：智慧大棚物联网）
```

## 前置条件

1. 后端已运行：项目根执行 `python run.py`（或托盘「启动后端」），浏览器可打开控制台。
2. 设置页已配置 **编译 LLM**（base_url / model / LLM_API_KEY）——编译环节必需。
3. 已启用 **大脑** 并配置 Embedding 与 LLM（设置页「大脑」分组）——索引 / 问答 / 图谱环节必需；未配置时脚本对应环节提示跳过，其余环节不受影响。

## 运行演示

```bat
cd /d <项目根>
.venv\Scripts\python scripts\demo\run_demo.py
```

脚本按序执行：

1. 前置检查（后端可达 / 编译 LLM / 大脑状态）；
2. 注入 4 份演示素材到 `inbox/manual/`（`meta.demo: true` + 标题带「【演示】」前缀，`source=manual`）；
3. 触发编译（`POST /api/compile/trigger scope=all`）并轮询等待队列清空；
4. 校验演示素材编译产出的知识条目（concepts / lessons / queries 等五类）；
5. 触发大脑索引（`POST /api/brain/index`），输出图谱规模并做一次问答冒烟；
6. 打印**预设问题清单（含预期答案要点）**与演示操作指引——演示者照读即可。

可选参数：`--base-url http://127.0.0.1:8765`（后端地址）、`--timeout 900`（编译等待截止秒数）、`--no-ask`（跳过问答冒烟）。

> 提示：编译走真实 LLM，4 份素材约需数分钟；种子内容不变时重复运行会命中编译缓存，速度显著加快。引擎/服务异常时脚本会打印具体提示后以非零码退出，不会产生半成品标记。

## 清理演示产物

```bat
.venv\Scripts\python scripts\demo\cleanup_demo.py
```

- 移除范围：`inbox` 中 `meta.demo: true` 的演示素材 + `knowledge` 中 sources 引用这些素材的知识条目（经后端 `DELETE /api/knowledge`：删文件 + 重建 index.md + 大脑索引同步清理）。
- **必须在后端在线时运行**（大脑索引一致性由后端完成）；编译队列运行中会拒绝执行。
- 清理完成后复核归零并提示；`knowledge/log.md` 为追加式编译历史留痕，按设计保留。

## 演示素材设计

| 种子 | 内容 | 预期产出 |
|------|------|----------|
| 01-kickoff-meeting | 项目启动会纪要（含决策 D-2026-001） | decisions / lessons 类条目 |
| 02-lora-nbiot-notes | LoRa vs NB-IoT 技术调研 | concepts / connections 类条目 |
| 03-greenhouse-incident | 温控误报事件复盘 | lessons 类条目 |
| 04-edge-gateway-question | 边缘网关待研究问题 | queries 类条目 |

预设问题（`run_demo.py` 结尾也会打印）：

1. 智慧大棚项目的通信方案为什么选 LoRa？NB-IoT 什么时候用？
2. 大棚温控误报事件的根因和改进措施是什么？
3. 边缘计算网关二期有哪些待研究问题？
