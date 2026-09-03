"""落盘 FIFO 串行协调（T-206 REQ-206）。

Ported from nashsu/llm_wiki (GPL-3.0) — src/lib/ingest-commit-coordinator.ts。
原实现用 Promise 链：准备（LLM 提炼）可并发，落盘（写文件）按任务启动顺序
严格串行。Python 侧以 threading.Condition + 序号票据等价实现：

- reserve() 按调用顺序发放票据（任务启动序）
- 进入 with 块时阻塞等待轮到自己，块内即落盘临界区
- 退出（含异常）时轮次前移并唤醒后续；release() 幂等
- 失败/取消的任务必须释放未使用的轮次，否则后续永久卡死
"""
import threading
from collections.abc import Callable
from typing import TypeVar

T = TypeVar("T")


class CommitReservation:
    def __init__(self, coordinator: "CommitCoordinator", ticket: int):
        self._coord = coordinator
        self._ticket = ticket
        self._released = False

    def wait_turn(self) -> None:
        """阻塞直到轮到本票据（此前所有票据均已释放）。"""
        with self._coord._cv:
            while self._ticket != self._coord._turn:
                self._coord._cv.wait()

    def release(self) -> None:
        """释放轮次（幂等）：无论是否进入过临界区都必须调用。"""
        with self._coord._cv:
            if self._released:
                return
            self._released = True
            self._coord._turn += 1
            self._coord._cv.notify_all()

    def __enter__(self) -> "CommitReservation":
        self.wait_turn()
        return self

    def __exit__(self, *exc) -> bool:
        self.release()
        return False

    def run_commit(self, operation: Callable[[], T]) -> T:
        """等轮次 → 执行 → finally 释放（对应源码 runCommit）。"""
        self.wait_turn()
        try:
            return operation()
        finally:
            self.release()


class CommitCoordinator:
    def __init__(self):
        self._cv = threading.Condition()
        self._next = 0   # 已发放的最大票据号
        self._turn = 0   # 当前允许进入的票据号

    def reserve(self) -> CommitReservation:
        """发放一个落盘轮次。用法：

            with coordinator.reserve():   # 进入即串行临界区
                ...写文件...
        """
        with self._cv:
            ticket = self._next
            self._next += 1
        return CommitReservation(self, ticket)
