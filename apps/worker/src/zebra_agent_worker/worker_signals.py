"""Scoped CLI stop requests; ongoing work drains through existing Worker code."""
import signal
from collections.abc import Callable, Iterator
from contextlib import ExitStack, contextmanager
from threading import current_thread, main_thread
from types import FrameType

from zebra_agent_worker.worker_shutdown import begin_worker_drain


@contextmanager
def worker_stop_signals() -> Iterator[Callable[[], bool]]:
    # Signal callbacks and CLI polling share the owning main thread.
    stopping = False

    def request_stop(_signal: int, _frame: FrameType | None) -> None:
        nonlocal stopping
        stopping = True
        begin_worker_drain()

    with ExitStack() as restore:
        if current_thread() is main_thread():
            for signum in (signal.SIGINT, signal.SIGTERM):
                previous = signal.signal(signum, request_stop)
                restore.callback(signal.signal, signum, previous)
        yield lambda: stopping
