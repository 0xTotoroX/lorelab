"""Bounded item scheduling; enumeration and result ordering stay with the caller.

[INPUT]: TaskItem snapshots, resolved bundle paths and the item action.
[OUTPUT]: run_items; joins all started work before returning or raising.
[POS]: tasks item scheduler; no providers, persistence or model calls.
[PROTOCOL]: 变更时更新此头部，然后检查 AGENTS.md
"""

from __future__ import annotations

import signal
from collections import deque
from collections.abc import Callable
from concurrent.futures import FIRST_COMPLETED, Future, ThreadPoolExecutor, wait
from contextvars import copy_context
from pathlib import Path
from threading import current_thread, main_thread

from soota.tasks.models import TaskItem


def run_items(
    rows: list[TaskItem],
    *,
    workers: int,
    folder: Callable[[TaskItem], Path],
    action: Callable[[TaskItem], None],
) -> None:
    if workers == 1:
        for row in rows:
            action(row.model_copy(deep=True))
        return

    # Different identities can resolve to the same bundle (file + bundle input,
    # symlink, sanitized source ID). Keep those rows in their original order.
    groups: dict[Path, deque[TaskItem]] = {}
    for row in rows:
        groups.setdefault(folder(row).resolve(), deque()).append(row.model_copy(deep=True))
    ready = deque(groups.values())
    running: dict[Future[None], deque[TaskItem]] = {}
    pool = ThreadPoolExecutor(max_workers=workers, thread_name_prefix="soota-item")
    try:
        while ready or running:
            while ready and len(running) < workers:
                group = ready.popleft()
                # A distinct Context per submission carries the shared budget
                # without entering the same Context concurrently in two threads.
                future = pool.submit(copy_context().run, action, group.popleft())
                running[future] = group
            done, _ = wait(running, return_when=FIRST_COMPLETED)
            for future in done:
                group = running.pop(future)
                future.result()
                if group:
                    ready.append(group)
    finally:
        # Ctrl-C stops new submissions. A second Ctrl-C must not break join and
        # release the job lock while a worker can still write an artifact/job.
        if current_thread() is main_thread():
            previous = signal.signal(signal.SIGINT, signal.SIG_IGN)
            try:
                pool.shutdown(wait=True, cancel_futures=True)
            finally:
                signal.signal(signal.SIGINT, previous)
        else:
            pool.shutdown(wait=True, cancel_futures=True)
