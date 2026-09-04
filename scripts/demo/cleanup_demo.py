"""M5 演示清理（T-508 / REQ-508）：一键移除演示产物，数据回到演示前状态。

移除范围：
- inbox 中 meta.demo=true 的演示素材（直接删除文件）；
- knowledge 中 frontmatter sources 引用了演示素材的知识条目
  （经后端 DELETE /api/knowledge：删文件 + index.md 重建 + 大脑索引同步清理）。

说明：
- knowledge/log.md 为追加式编译历史留痕，不做改写；
- 前置要求后端已运行——大脑索引一致性由后端在删除条目时同步完成，
  离线状态下脚本拒绝执行（提示先启动后端）。

用法（项目根）：.venv/Scripts/python scripts/demo/cleanup_demo.py
"""
import argparse
import json
import sys
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))


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
        raise RuntimeError(f"HTTP {e.code}: {detail}") from e
    except urllib.error.URLError as e:
        raise RuntimeError(f"后端不可达（{e.reason}）——清理需要后端在线以同步大脑索引，"
                           "请先 python run.py 启动后端") from e


def main() -> int:
    ap = argparse.ArgumentParser(description="KnowSeq 演示产物清理")
    ap.add_argument("--base-url", default="http://127.0.0.1:8765")
    args = ap.parse_args()

    from app.capture.inbox import Inbox
    from app.config import Config
    from app.compile.materials import split_frontmatter
    from app.compile.schema import CATEGORIES

    cfg = Config()
    inbox = Inbox(cfg.inbox_dir)

    # 前置：后端在线（大脑索引一致性依赖后端删除条目）
    try:
        _http(args.base_url, "GET", "/api/status")
        print("√ 后端在线")
    except RuntimeError as e:
        print(f"× {e}")
        return 1
    # 避开编译进行中的窗口（此时删除素材会使任务失败）
    st = _http(args.base_url, "GET", "/api/compile/status")
    q = st.get("queue", {})
    if int(q.get("pending", 0)) or int(q.get("processing", 0)):
        print("× 编译队列正在运行（pending/processing > 0），请等待编译完成后再清理")
        return 1
    print("√ 编译队列空闲")

    # 1) 找出并删除演示素材
    demo_rels: list[str] = []
    for mat in inbox.list_materials():
        rel = Path(mat["path"]).as_posix()  # 条目 frontmatter sources 为 posix 格式
        detail = inbox.read_material(rel) or {}
        meta = detail.get("meta") or {}
        if meta.get("demo") is True:
            demo_rels.append(rel)
    print(f"\n[1/3] 演示素材 {len(demo_rels)} 条")
    for rel in demo_rels:
        (inbox.root / rel).unlink(missing_ok=True)
        print(f"  - inbox/{rel}")

    # 2) 找出 sources 引用演示素材的知识条目，经后端删除（含大脑索引清理）
    hits: list[str] = []
    for cat in CATEGORIES:
        for mdf in sorted((cfg.knowledge_dir / cat).glob("*.md")):
            meta, _ = split_frontmatter(mdf.read_text(encoding="utf-8"))
            sources = meta.get("sources") or []
            if any(s in demo_rels for s in sources):
                hits.append(mdf.relative_to(cfg.knowledge_dir).as_posix())
    print(f"\n[2/3] 演示知识条目 {len(hits)} 条（经后端删除：文件 + index.md + 大脑索引）")
    for rel in hits:
        try:
            res = _http(args.base_url, "DELETE",
                        f"/api/knowledge?path={urllib.parse.quote(rel)}")
            brain = res.get("brain") or {}
            print(f"  - knowledge/{rel}  index_updated={res.get('index_updated')}"
                  f"  brain_removed={brain.get('indexed', brain.get('doc_id') is not None)}")
        except RuntimeError as e:
            print(f"  × knowledge/{rel}：{e}")

    # 3) 复核：演示产物应清零
    left_mat = 0
    for mat in inbox.list_materials():
        meta = (inbox.read_material(mat["path"]) or {}).get("meta") or {}
        if meta.get("demo") is True:
            left_mat += 1
    left_ent = 0
    for cat in CATEGORIES:
        for mdf in (cfg.knowledge_dir / cat).glob("*.md"):
            meta, _ = split_frontmatter(mdf.read_text(encoding="utf-8"))
            if any(s in demo_rels for s in (meta.get("sources") or [])):
                left_ent += 1
    print(f"\n[3/3] 复核：残留演示素材 {left_mat} 条 · 残留演示条目 {left_ent} 条")
    if left_mat or left_ent:
        print("× 仍有残留，请检查上方报错后重跑本脚本")
        return 1
    print("√ 清理完成，数据已回到演示前状态（knowledge/log.md 历史留痕按设计保留）")
    return 0


if __name__ == "__main__":
    sys.exit(main())
