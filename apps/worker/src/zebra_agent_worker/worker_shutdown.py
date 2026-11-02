"""Cloud process deadline: retain real ownership until drained or the process exits."""

from __future__ import annotations

import math
import os
from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from threading import RLock, Timer

WORKER_DRAIN_SECONDS = 30.0
_current: ContextVar[_ShutdownDeadline | None] = ContextVar("worker_shutdown", default=None)


class _ShutdownDeadline:
    def __init__(self, seconds: float) -> None:
        self.seconds = seconds
        # SIGTERM can reenter begin on the main thread while it owns this lock.
        self._lock = RLock()
        self._timer: Timer | None = None
        self._finished = False

    def begin(self) -> None:
        with self._lock:
            if self._timer is None and not self._finished:
                self._timer = Timer(self.seconds, self._expire)
                self._timer.daemon = True
                self._timer.start()

    def _expire(self) -> None:
        with self._lock:
            if self._finished:
                return
            # ponytail: Python cannot kill a stuck thread safely. Only the cloud
            # process root owns this last resort; durable lease recovery owns
            # unfinished work. A supervisor grace period must exceed this budget.
            try:
                diagnostic = os.dup(2)
                try:
                    os.set_blocking(diagnostic, False)
                    os.write(diagnostic, b"worker_shutdown_deadline_exceeded "
                             b"resources_released=false\n")
                finally:
                    os.close(diagnostic)
            except OSError:
                pass
            finally:
                os._exit(75)

    def finish(self) -> None:
        with self._lock:
            self._finished = True
            timer = self._timer
            if timer is not None:
                timer.cancel()
        if timer is not None:
            timer.join()


def begin_worker_drain() -> None:
    if (deadline := _current.get()) is not None:
        deadline.begin()


@contextmanager
def worker_shutdown_deadline(
    *, enabled: bool = True, timeout_seconds: float = WORKER_DRAIN_SECONDS,
) -> Iterator[None]:
    if type(timeout_seconds) not in (int, float) or not math.isfinite(timeout_seconds) \
            or timeout_seconds <= 0:
        raise ValueError("worker shutdown deadline must be finite and positive")
    deadline = _ShutdownDeadline(timeout_seconds) if enabled else None
    token = _current.set(deadline)
    try:
        yield
    finally:
        if deadline is not None:
            deadline.finish()
        _current.reset(token)
