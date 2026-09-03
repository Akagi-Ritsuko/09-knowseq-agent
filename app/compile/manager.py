"""编译管理器（T-201 REQ-201 / T-205~208 接入）。

生命周期与轮询框架：扫描 inbox 中 compiled: false 的素材 → 持久化编译队列
（CompileQueue）→ worker 经 runner 执行两步 CoT 提炼管线（pipeline.compile_one）
产出 knowledge/ 条目。幂等由三层保证：frontmatter compiled 标记
（materials.mark_compiled）、内容缓存（IngestCache）、队列去重（upsert）。
"""
import threading
from dataclasses import asdict
from pathlib import Path

from ..capture.inbox import Inbox
from ..config import Config
from .cache import IngestCache, sha256_text
from .dedup import detect_duplicate_groups, extract_entity_summary, merge_duplicate_group
from .enrich import enrich_wikilinks
from .lint import lint_knowledge
from .llm_client import has_usable_llm
from .materials import is_compiled, mark_compiled
from .pipeline import CompileCancelled, PipelineContext, compile_one
from .queue import CompileTask, CompileQueue
from .review_store import ReviewStore, from_block
from .schema import CATEGORIES


class CompileManager:
    def __init__(self, config: Config, inbox: Inbox):
        self.config = config
        self.inbox = inbox
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._lock = threading.Lock()      # 保护 last_scan / last_error / last_warnings
        self._last_error: str | None = None
        self._last_warnings: list[str] = []  # 最近一次编译的警告（管线非致命问题）
        self.last_scan: list[str] = []     # 最近一次扫描的待编译清单快照
        # 运行态（.knowseq/）与 knowledge/ 同级，便于测试整体重定向
        base = self.config.knowledge_dir.parent
        self._runtime = base / ".knowseq"
        self.cache = IngestCache(base, root=self.config.knowledge_dir)
        self.queue = CompileQueue(
            base, runner=self._run_task,
            worker_limit=int(self.config.get("compile.queue.concurrency", 1)),
            max_retries=int(self.config.get("compile.queue.max_retries", 3)))
        self.reviews = ReviewStore(base)  # REVIEW 项闭环（T-210 REQ-210）

    # ---- knowledge/ 初始化 ----
    def ensure_knowledge(self) -> Path:
        root = self.config.knowledge_dir
        for cat in CATEGORIES:
            (root / cat).mkdir(parents=True, exist_ok=True)
        index = root / "index.md"
        if not index.exists():
            lines = ["# 知识库索引", ""]
            for cat in CATEGORIES:
                lines += [f"## {cat}", ""]
            index.write_text("\n".join(lines), encoding="utf-8")
        log = root / "log.md"
        if not log.exists():
            log.write_text("# 编译日志\n", encoding="utf-8")
        return root

    # ---- 生命周期 ----
    def start(self) -> None:
        if not self.config.get("compile.enabled", True):
            return
        self.ensure_knowledge()
        self.queue.start()
        if self._thread and self._thread.is_alive():
            return
        self._stop.clear()
        self._thread = threading.Thread(target=self._run_loop, name="compile-poll", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        if self._thread:
            self._thread.join(timeout=5)
            self._thread = None
        self.queue.stop()

    def _run_loop(self) -> None:
        interval = max(5, int(self.config.get("compile.poll_interval", 30)))
        while not self._stop.wait(interval):
            try:
                self.poll_once()
            except Exception as e:  # noqa: BLE001
                with self._lock:
                    self._last_error = str(e)

    # ---- 扫描与触发 ----
    def _scan_pending(self) -> list[str]:
        out = []
        for p in sorted(self.inbox.root.rglob("*.md")):
            if p.name.startswith("."):
                continue
            if not is_compiled(p):
                out.append(str(p.relative_to(self.inbox.root)).replace("\\", "/"))
        return out

    def poll_once(self) -> None:
        """自动轮询：新出现的未编译素材入队（不复活既有任务）。"""
        if not self.config.get("compile.auto", True):
            return
        uncompiled = self._scan_pending()
        for rel in uncompiled:
            self.queue.upsert(rel, revive=False)
        with self._lock:
            self.last_scan = uncompiled

    def trigger_all(self) -> int:
        """手动触发：全部未编译素材（重新）入队（复活 stopped 任务）。"""
        rels = self._scan_pending()
        for rel in rels:
            self.queue.upsert(rel, revive=True)
        with self._lock:
            self.last_scan = rels
        return len(rels)

    def _llm_ready(self) -> bool:
        return has_usable_llm(self.config)

    # ---- 单任务执行（队列 runner） ----
    def _run_task(self, task: CompileTask, cancel_event: threading.Event,
                  coordinator) -> list[str]:
        """缓存命中直接推进标记；否则提炼（T-207）→ 写缓存 → 标记。"""
        src = self.inbox.root / task.source_path
        content = src.read_text(encoding="utf-8")
        digest = sha256_text(content)
        hit = self.cache.get(task.source_path, digest)
        if hit is None and not self._llm_ready():  # 缓存命中无需 LLM
            raise RuntimeError("LLM 未配置：请先设置 base_url / model / LLM_API_KEY")
        with coordinator.reserve():  # 落盘临界区：按任务启动序 FIFO 串行
            if hit is not None:
                files = list(hit.files_written)
            else:
                try:
                    files = self._pipeline(task, content, cancel_event)
                except CompileCancelled:
                    return []  # 用户取消：队列按 yanked 丢弃，不计失败
                self.cache.put(task.source_path, digest, files)
            mark_compiled(src)
        return files

    def _pipeline(self, task: CompileTask, content: str,
                  cancel_event: threading.Event) -> list[str]:
        """提炼管线（T-207/T-208 两步 CoT 编排接入点）：返回 knowledge/ 相对路径。"""
        ctx = PipelineContext(
            config=self.config,
            knowledge_dir=self.config.knowledge_dir,
            runtime_dir=self._runtime,
            content=content,
            source_identity=task.source_path,
            cancel_event=cancel_event,
        )
        outcome = compile_one(ctx)  # CompileIncompleteError 上抛 → 队列重试
        if outcome.reviews:  # REVIEW 块入库（同 id 内容派生，重复出现自动合并）
            self.reviews.add(from_block(b, task.source_path) for b in outcome.reviews)
        with self._lock:
            self._last_warnings = list(outcome.warnings)
        return outcome.files

    # ---- 手动控制台操作（REQ-213） ----
    def trigger_path(self, rel: str) -> int:
        """手动触发单条素材（scope=path）：按相对路径入队（复活 stopped 任务）。"""
        rel = (rel or "").strip().replace("\\", "/")
        if not rel:
            return 0
        self.queue.upsert(rel, revive=True)
        return 1

    def _ctx(self, *, content: str = "", source_identity: str = "",
             cancel_event: threading.Event | None = None) -> PipelineContext:
        return PipelineContext(
            config=self.config,
            knowledge_dir=self.config.knowledge_dir,
            runtime_dir=self._runtime,
            content=content,
            source_identity=source_identity,
            cancel_event=cancel_event,
        )

    def run_lint(self) -> list[dict]:
        """手动结构化 lint（纯本地无 LLM）：全库检查返回可 JSON 序列化问题列表。"""
        return [asdict(i) for i in lint_knowledge(self.config.knowledge_dir)]

    def run_dedup(self, cancel_event: threading.Event | None = None) -> dict:
        """手动 dedup：LLM 批扫检测 → 逐组合并，返回 {scanned, detected, merged}。

        单组合并失败不阻断整轮（继续下一组）；cancel_event 置位即中断。
        """
        ctx = self._ctx(cancel_event=cancel_event)
        summaries = extract_entity_summary(self.config.knowledge_dir)
        groups = detect_duplicate_groups(summaries, ctx)
        merged: list[dict] = []
        for g in groups:
            if cancel_event is not None and cancel_event.is_set():
                break
            try:
                res = merge_duplicate_group(g, ctx)
            except Exception:  # noqa: BLE001 — 合并失败跳过该组，不阻断整轮
                continue
            merged.append({"slugs": g.get("slugs", []), "canonical_path": res.canonical_path})
        return {"scanned": len(summaries), "detected": len(groups), "merged": merged}

    def run_enrich(self, *, dry_run: bool = False,
                   cancel_event: threading.Event | None = None) -> dict:
        """手动 enrich-wikilinks（REQ-212）；dry_run 只报告不写盘。"""
        ctx = self._ctx(cancel_event=cancel_event)
        res = enrich_wikilinks(self.config.knowledge_dir, ctx, dry_run=dry_run)
        return {
            "scanned": res.scanned,
            "dry_run": res.dry_run,
            "changes": [asdict(c) for c in res.changes],
        }

    # ---- 状态 ----
    def status(self) -> dict:
        with self._lock:
            base = {
                "enabled": self.config.get("compile.enabled", True),
                "llm_ready": self._llm_ready(),
                "last_scan": list(self.last_scan),
                "last_error": self._last_error,
                "last_warnings": list(self._last_warnings),
            }
        base["queue"] = self.queue.summary()
        base["pending"] = [t["source_path"] for t in self.queue.snapshot()
                           if t["status"] == "pending"]
        base["reviews_open"] = len(self.reviews.list("open"))
        return base
