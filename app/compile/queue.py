"""持久化编译队列与调度（T-206 REQ-206）。

Ported from nashsu/llm_wiki (GPL-3.0) — src/lib/ingest-queue.ts（简化版：
单项目，无 projectId/folderContext/项目切换逻辑）。

- 任务状态机：pending → processing → (完成移除 | failed | cancelled)；失败
  未达上限回 pending 重试（默认 3 次）
- 持久化 `<base_dir>/.knowseq/compile-queue.json`；done 任务不入盘；
  重启加载时 processing 一律重置回 pending（进程被 kill 也能恢复）
- 429/限流：全队列暂停 15 分钟自动恢复，兄弟 processing 任务全部中止回
  pending；用户 pause() 仅内存态，重启即恢复运行
- 内置 worker 线程池（1-5 默认 1）；落盘经 CommitCoordinator 按任务
  启动顺序 FIFO 串行
"""
import json
import re
import threading
import time
import uuid
from collections.abc import Callable
from dataclasses import asdict, dataclass, field
from pathlib import Path

from .commit import CommitCoordinator

MAX_RETRIES = 3
USAGE_LIMIT_PAUSE_S = 15 * 60  # 429 后自动恢复间隔
USAGE_LIMIT_RE = re.compile(r"\b429\b|rate[_\s-]*limit|usage\s+limit|quota|too many requests", re.IGNORECASE)


def is_usage_limit_error(message: str) -> bool:
    """限流类错误判定（对应源码 isUsageLimitError）。"""
    return bool(USAGE_LIMIT_RE.search(message))


def _generate_id() -> str:
    return f"compile-{int(time.time() * 1000)}-{uuid.uuid4().hex[:6]}"


@dataclass
class CompileTask:
    id: str
    source_path: str   # 相对 inbox 的路径（正斜杠）
    status: str = "pending"
    added_at: float = field(default_factory=time.time)
    retry_count: int = 0
    error: str | None = None

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict) -> "CompileTask":
        return cls(
            id=d["id"], source_path=d["source_path"],
            status=d.get("status", "pending"), added_at=d.get("added_at", 0.0),
            retry_count=d.get("retry_count", 0), error=d.get("error"))


# runner(task, cancel_event, coordinator) -> 写入 knowledge/ 的相对路径列表
Runner = Callable[[CompileTask, threading.Event, CommitCoordinator], list[str]]


class CompileQueue:
    def __init__(self, base_dir: Path, runner: Runner | None = None, *,
                 worker_limit: int = 1, max_retries: int = MAX_RETRIES,
                 usage_limit_pause: float = USAGE_LIMIT_PAUSE_S):
        self._path = Path(base_dir) / ".knowseq" / "compile-queue.json"
        self._runner = runner
        self._max_retries = max_retries
        self._usage_pause = usage_limit_pause
        self._worker_limit = max(1, min(5, int(worker_limit) or 1))  # clamp 1-5
        self._cv = threading.Condition()
        self._tasks: list[CompileTask] = []
        self._runs: dict[str, threading.Event] = {}   # task_id → 运行取消事件
        self._workers: list[threading.Thread] = []
        self._stop_flag = False
        self._paused = False
        self._resume_at: float | None = None          # time.monotonic 时刻
        self._completed = 0
        self.coordinator = CommitCoordinator()
        self._load()

    # ---- 持久化 ----
    def _load(self) -> None:
        try:
            raw = self._path.read_text(encoding="utf-8")
            tasks = [CompileTask.from_dict(d) for d in json.loads(raw)]
        except Exception:  # noqa: BLE001  缺失/损坏视为空队列
            return
        for t in tasks:  # 重启恢复：被打断的 processing 一律重置回 pending
            if t.status == "processing":
                t.status = "pending"
        self._tasks = tasks

    def _save_locked(self) -> None:
        """持久化（过滤 done；调用方必须已持有 _cv）。"""
        try:
            self._path.parent.mkdir(parents=True, exist_ok=True)
            payload = [t.to_dict() for t in self._tasks if t.status != "done"]
            self._path.write_text(json.dumps(payload, ensure_ascii=False, indent=2),
                                  encoding="utf-8")
        except OSError:
            pass  # 持久化尽力而为，内存队列始终是权威状态

    def _find_locked(self, task_id: str) -> CompileTask | None:
        return next((t for t in self._tasks if t.id == task_id), None)

    # ---- 任务操作 ----
    def upsert(self, source_path: str, revive: bool = True) -> str:
        """按素材路径入队。已有同源非 done 任务时：

        - revive=True（手动触发）：stopped 任务复活重跑；processing 任务
          存在时若已有 pending 副本则复用，否则新建 pending 副本
        - revive=False（自动轮询）：一律不动现有任务，防止失败任务被
          无限复活重试
        """
        with self._cv:
            existing = next(
                (t for t in self._tasks
                 if t.source_path == source_path and t.status != "done"), None)
            if existing and not revive:
                return existing.id
            if existing:
                if existing.status in ("pending", "failed", "cancelled"):
                    existing.status = "pending"
                    existing.error = None
                    existing.retry_count = 0
                    return existing.id
                rerun = next(  # processing 中：复用或新建 pending 重跑副本
                    (t for t in self._tasks
                     if t.source_path == source_path and t.status == "pending"), None)
                if rerun:
                    return rerun.id
            task = CompileTask(id=_generate_id(), source_path=source_path)
            self._tasks.append(task)
            self._save_locked()
            self._cv.notify_all()
            return task.id

    def take(self) -> CompileTask | None:
        """取下一个 pending 任务并标记 processing（worker 原语）。"""
        with self._cv:
            return self._take_locked()

    def _take_locked(self) -> CompileTask | None:
        if self._paused or self._stop_flag:
            return None
        task = next(
            (t for t in self._tasks
             if t.status == "pending" and t.id not in self._runs), None)
        if not task:
            return None
        task.status = "processing"
        self._runs[task.id] = threading.Event()
        self._save_locked()
        return task

    def cancel_event(self, task_id: str) -> threading.Event | None:
        with self._cv:
            return self._runs.get(task_id)

    def complete(self, task_id: str) -> bool:
        """任务成功：从队列移除（done 不入盘）。"""
        with self._cv:
            task = self._find_locked(task_id)
            if not task or task.status != "processing":
                return False
            self._tasks.remove(task)
            self._runs.pop(task.id, None)
            self._completed += 1
            if not self._tasks:
                self._completed = 0  # 队列清空即重置计数（对应 resetQueueAccounting）
            self._save_locked()
            self._cv.notify_all()
            return True

    def fail(self, task_id: str, error: str) -> None:
        """任务失败：限流 → 全局暂停并定时自动恢复；否则重试计数，达上限 failed。"""
        with self._cv:
            task = self._find_locked(task_id)
            if not task or task.status != "processing":
                return
            event = self._runs.pop(task_id, None)  # 手动驱动时无 _execute 兜底清理
            if event:
                event.set()
            if is_usage_limit_error(error):
                task.status = "pending"
                task.error = f"已因服务商限流暂停：{error}"
                self._pause_locked(self._usage_pause, task.error)
                return
            task.retry_count += 1
            task.error = error
            task.status = "failed" if task.retry_count >= self._max_retries else "pending"
            self._save_locked()
            self._cv.notify_all()

    def retry(self, task_id: str) -> bool:
        """手动重试 failed/cancelled 任务。"""
        with self._cv:
            task = self._find_locked(task_id)
            if not task or task.status not in ("failed", "cancelled"):
                return False
            task.status = "pending"
            task.error = None
            task.retry_count = 0
            self._save_locked()
            self._cv.notify_all()
            return True

    def cancel(self, task_id: str) -> bool:
        """取消任务；in-flight 的运行通过取消事件自行退出。"""
        with self._cv:
            task = self._find_locked(task_id)
            if not task or task.status in ("done", "cancelled"):
                return False
            if task.status == "processing":
                event = self._runs.pop(task_id, None)
                if event:
                    event.set()
            task.status = "cancelled"
            task.error = None
            if not any(t.status in ("pending", "processing") for t in self._tasks):
                self._paused = False
                self._resume_at = None
            self._save_locked()
            self._cv.notify_all()
            return True

    # ---- 暂停/恢复 ----
    def _pause_locked(self, seconds: float | None, message: str | None = None) -> None:
        """暂停并中止全部 in-flight（回 pending）。调用方必须已持有 _cv。"""
        self._paused = True
        self._resume_at = time.monotonic() + seconds if seconds and seconds > 0 else None
        for t in self._tasks:
            if t.status != "processing":
                continue
            if message and not t.error:
                t.error = message
            t.status = "pending"
            event = self._runs.pop(t.id, None)
            if event:
                event.set()
        self._save_locked()
        self._cv.notify_all()

    def pause(self, seconds: float | None = None) -> None:
        """暂停调度；seconds>0 时到点自动恢复（429 路径）。仅内存态。"""
        with self._cv:
            self._pause_locked(seconds)

    def resume(self) -> None:
        with self._cv:
            self._paused = False
            self._resume_at = None
            self._cv.notify_all()

    # ---- 内置调度 ----
    def start(self) -> None:
        if self._runner is None or self._workers:
            return
        with self._cv:  # 暂停是会话内控制，重启/重新启动即恢复（对应 restoreQueue）
            self._paused = False
            self._resume_at = None
        for i in range(self._worker_limit):
            th = threading.Thread(target=self._worker, name=f"compile-worker-{i}", daemon=True)
            self._workers.append(th)
            th.start()

    def stop(self) -> None:
        with self._cv:
            self._stop_flag = True
            for event in self._runs.values():  # 中止 in-flight 的 LLM 流式调用
                event.set()
            self._cv.notify_all()
        for th in self._workers:
            th.join(timeout=5)
        with self._cv:
            self._workers.clear()
            self._stop_flag = False
            self._runs.clear()         # 事件已置位；清理残留防 take 永久跳过
            for t in self._tasks:      # processing 回 pending，保证可重启续跑
                if t.status == "processing":
                    t.status = "pending"
            self._paused = False
            self._resume_at = None
            self._save_locked()

    def _worker(self) -> None:
        while True:
            with self._cv:
                if self._stop_flag:
                    return
                if self._paused:
                    if self._resume_at is not None and time.monotonic() >= self._resume_at:
                        self._paused = False
                        self._resume_at = None
                        self._cv.notify_all()
                    else:
                        self._cv.wait(timeout=1.0)
                    continue
                task = self._take_locked()
                if task is None:
                    self._cv.wait(timeout=1.0)
                    continue
                event = self._runs[task.id]
                coordinator = self.coordinator
            self._execute(task, event, coordinator)

    def _execute(self, task: CompileTask, event: threading.Event,
                 coordinator: CommitCoordinator) -> None:
        try:
            files = self._runner(task, event, coordinator) if self._runner else []
            if self._yanked(task.id, event):
                return  # 已被 pause/cancel 拽回，成败都不再记录
            if not files:
                raise RuntimeError("编译未产出任何条目")
            self.complete(task.id)
        except Exception as e:  # noqa: BLE001
            if self._yanked(task.id, event):
                return
            self.fail(task.id, str(e))
        finally:
            with self._cv:
                self._runs.pop(task.id, None)
                self._cv.notify_all()

    def _yanked(self, task_id: str, event: threading.Event) -> bool:
        """任务是否已被暂停/取消/移出（不再属于本次运行）。"""
        with self._cv:
            task = self._find_locked(task_id)
            return event.is_set() or task is None or task.status != "processing"

    # ---- 状态 ----
    def snapshot(self) -> list[dict]:
        with self._cv:
            return [t.to_dict() for t in self._tasks]

    def summary(self) -> dict:
        with self._cv:
            return {
                "pending": sum(t.status == "pending" for t in self._tasks),
                "processing": sum(t.status == "processing" for t in self._tasks),
                "failed": sum(t.status == "failed" for t in self._tasks),
                "cancelled": sum(t.status == "cancelled" for t in self._tasks),
                "completed": self._completed,
                "total": len(self._tasks),
                "paused": self._paused,
            }
