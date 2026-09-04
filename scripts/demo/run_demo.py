"""M5 演示脚本（T-508 / REQ-508）：全链路演示——注入演示素材 → 触发编译 →
触发大脑索引 → 冒烟验证问答与图谱 → 输出预设问题清单与演示指引。

用法（项目根，使用项目 venv 的 Python）：

    .venv/Scripts/python scripts/demo/run_demo.py
    .venv/Scripts/python scripts/demo/run_demo.py --base-url http://127.0.0.1:8765 --no-ask

前置条件：
- 后端已运行（python run.py，或托盘「启动后端」）；
- 设置页已配置编译 LLM（base_url / model / LLM_API_KEY）；
- 已启用大脑并配置 Embedding 与 LLM（问答 / 图谱环节需要，未配置时对应环节提示跳过）。

演示素材统一带 meta.demo=true 标记（source=manual，标题带「【演示】」前缀），
不污染真实数据；演示后用 cleanup_demo.py 一键清理
（inbox 素材 / knowledge 条目 / 大脑索引同步移除）。
"""
import argparse
import json
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

SEED_DIR = Path(__file__).resolve().parent / "seed"

# 预设问题清单（脚本结尾输出，供演示者照读）
PRESET_QUESTIONS = [
    {
        "q": "智慧大棚项目的通信方案为什么选 LoRa？NB-IoT 什么时候用？",
        "points": "LoRa 为主：覆盖/功耗/无流量费，适合设施农业连片场景；NB-IoT 用于无网关区域备份与露天大田分散场景；两者可共存，网关协议层抽象（决策 D-2026-001）",
    },
    {
        "q": "大棚温控误报事件的根因和改进措施是什么？",
        "points": "根因：传感器贴热源蓄热读数偏高 + 告警无滞回反复触发 + 无频率限制；改进：远离热源 1.5 米、2 度滞回、30 分钟告警间隔与升级告警；教训：告警可信度比灵敏度重要",
    },
    {
        "q": "边缘计算网关二期有哪些待研究问题？",
        "points": "本地推理 vs 云端推理（4 核 ARM 量化模型可行性）；模型增量更新的灰度与回滚；多棚协同与独立闭环的取舍",
    },
]


class DemoHttpError(Exception):
    def __init__(self, status: int, detail: str):
        super().__init__(f"HTTP {status}: {detail}")
        self.status = status
        self.detail = detail


def _http(base: str, method: str, path: str, payload=None,
          timeout: int = 120) -> dict:
    data = json.dumps(payload).encode("utf-8") if payload is not None else None
    req = urllib.request.Request(
        base.rstrip("/") + path, method=method, data=data,
        headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        detail = e.read().decode("utf-8", errors="replace")
        try:
            detail = json.loads(detail).get("detail", detail)
        except Exception:
            pass
        raise DemoHttpError(e.code, str(detail)) from e
    except urllib.error.URLError as e:
        raise DemoHttpError(0, f"后端不可达（{e.reason}）——请先启动后端 python run.py") from e
    except TimeoutError as e:  # socket 超时（Python 3.10+ 不经 URLError 包装）
        raise DemoHttpError(504, f"请求超时（{timeout}s）——服务端仍在处理，可稍后重试") from e


def parse_seed(path: Path) -> tuple[str, str]:
    """种子约定：第一行 `# 标题`，其余为正文。"""
    lines = path.read_text(encoding="utf-8").splitlines()
    title = lines[0].lstrip("#").strip() if lines else path.stem
    content = "\n".join(lines[1:]).strip()
    return title, content


def inject_seeds() -> list[str]:
    """经 Inbox.write_material 注入种子素材（meta.demo=true，dedup=False 可重复演示）。

    返回注入素材的相对路径列表（与知识条目 frontmatter sources 的取值同源）。
    """
    from app.capture.inbox import Inbox
    from app.config import Config

    inbox = Inbox(Config().inbox_dir)
    rels: list[str] = []
    print(f"\n[1/5] 注入演示素材（{len(list(SEED_DIR.glob('*.md')))} 份种子）")
    for seed in sorted(SEED_DIR.glob("*.md")):
        title, content = parse_seed(seed)
        path = inbox.write_material(
            "manual", f"【演示】{title}", content,
            meta={"demo": True, "seed": seed.name}, dedup=False)
        rel = path.relative_to(inbox.root).as_posix() if path else None
        rels.append(rel or "")
        print(f"  {'+' if rel else '×'} {seed.name} → {rel or '写入失败（内容为空）'}")
    return [r for r in rels if r]


def find_demo_entries(kd: Path, demo_rels: set[str]) -> list[str]:
    """扫五类知识条目，返回 sources 引用了演示素材的条目相对路径。"""
    from app.compile.materials import split_frontmatter
    from app.compile.schema import CATEGORIES

    out: list[str] = []
    for cat in CATEGORIES:
        for mdf in sorted((kd / cat).glob("*.md")):
            meta, _ = split_frontmatter(mdf.read_text(encoding="utf-8"))
            sources = meta.get("sources") or []
            if any(s in demo_rels for s in sources):
                out.append(mdf.relative_to(kd).as_posix())
    return out


def main() -> int:
    ap = argparse.ArgumentParser(description="KnowSeq 全链路演示脚本")
    ap.add_argument("--base-url", default="http://127.0.0.1:8765")
    ap.add_argument("--timeout", type=int, default=900,
                    help="等待编译完成的截止秒数（默认 900）")
    ap.add_argument("--no-ask", action="store_true",
                    help="跳过问答冒烟验证")
    args = ap.parse_args()
    base = args.base_url

    # 前置检查：后端可达 + 编译 LLM 就绪
    print("[0/5] 前置检查")
    try:
        status = _http(base, "GET", "/api/status")
    except DemoHttpError as e:
        print(f"  × {e.detail}")
        return 1
    print(f"  √ 后端可达（{base}）")
    comp = _http(base, "GET", "/api/compile/status")
    if not comp.get("llm_ready"):
        print("  × 编译 LLM 未配置：请先在设置页填写 base_url / model / LLM_API_KEY")
        return 1
    print("  √ 编译 LLM 就绪")
    try:
        brain = _http(base, "GET", "/api/brain/status")
        print(f"  {'√' if brain.get('ready') else '!'} 大脑{'就绪' if brain.get('ready') else '未就绪（索引/问答/图谱环节将提示跳过）'}")
    except DemoHttpError as e:
        print(f"  ! 大脑未启用（{e.detail}）——索引/问答/图谱环节将提示跳过")

    demo_rels = inject_seeds()
    if not demo_rels:
        print("  × 没有任何种子素材写入成功")
        return 1

    # 触发编译并等待队列清空
    print("\n[2/5] 触发编译（scope=all），等待队列清空…")
    trig = _http(base, "POST", "/api/compile/trigger", {"scope": "all"})
    print(f"  触发 {trig.get('triggered', 0)} 条素材编译")
    deadline = time.time() + args.timeout
    while True:
        st = _http(base, "GET", "/api/compile/status")
        q = st.get("queue", {})
        pend, proc = int(q.get("pending", 0)), int(q.get("processing", 0))
        if pend == 0 and proc == 0:
            break
        if time.time() > deadline:
            print(f"  × 等待编译超时（>{args.timeout}s，pending={pend} processing={proc}）")
            return 2
        print(f"  … pending={pend} processing={proc}", end="\r", flush=True)
        time.sleep(3)
    print("  √ 编译队列已清空" + " " * 20)
    if st.get("last_error"):
        print(f"  ! 编译器 last_error：{st['last_error']}")
    if int(q.get("failed", 0)):
        print(f"  ! 队列中有 {q['failed']} 条失败任务（详见 /api/compile/status）")

    # 验证知识条目产出
    from app.config import Config
    kd = Config().knowledge_dir
    entries = find_demo_entries(kd, set(demo_rels))
    print(f"\n[3/5] 演示素材编译产出知识条目 {len(entries)} 条")
    for rel in entries:
        print(f"  · knowledge/{rel}")

    # 触发大脑索引
    print("\n[4/5] 触发大脑索引（POST /api/brain/index）…")
    try:
        idx = _http(base, "POST", "/api/brain/index", {"rebuild": False}, timeout=1900)
        print(f"  √ 扫描 {idx.get('scanned')} · 新增 {idx.get('inserted')} · 跳过 {idx.get('skipped')}")
    except DemoHttpError as e:
        print(f"  ! 大脑索引未执行：{e.detail}")
        print("    （问答/图谱环节不可用；配置大脑后可单独重跑本步）")
        idx = None

    # 图谱 + 问答冒烟
    print("\n[5/5] 冒烟验证")
    try:
        g = _http(base, "GET", "/api/brain/graph", timeout=300)
        print(f"  · 图谱：{len(g.get('nodes', []))} 节点 · {len(g.get('edges', []))} 关系")
    except DemoHttpError as e:
        print(f"  · 图谱跳过：{e.detail}")
    if not args.no_ask and idx is not None:
        q0 = PRESET_QUESTIONS[0]["q"]
        try:
            ans = _http(base, "POST", "/api/brain/query",
                        {"query": q0, "mode": "hybrid", "top_k": 6}, timeout=600)
            refs = ans.get("contexts") or []
            print(f"  · 问答冒烟：「{q0}」")
            print(f"    回答 {len(ans.get('answer') or '')} 字 · 引用 {len(refs)} 条"
                  + (f"（首条 {refs[0]['file_path']}）" if refs else ""))
        except DemoHttpError as e:
            print(f"  · 问答冒烟跳过：{e.detail}")

    # 预设问题清单与演示指引
    print("\n========== 预设问题清单（演示者照读） ==========")
    for i, item in enumerate(PRESET_QUESTIONS, 1):
        print(f"Q{i}. {item['q']}\n    预期答案要点：{item['points']}")
    print("\n========== 演示指引 ==========")
    print(f"1. 浏览器打开 {base}/ → 左侧「问答」输入预设问题，观察引用卡片并点击跳转知识条目")
    print("2. 「图谱」页查看演示素材新增的实体与关系（可与演示前节点数对比）")
    print("3. 「素材」页按来源「手动导入」筛选可见全部【演示】素材")
    print("4. 演示结束：.venv/Scripts/python scripts/demo/cleanup_demo.py 一键清理")
    return 0


if __name__ == "__main__":
    sys.exit(main())
