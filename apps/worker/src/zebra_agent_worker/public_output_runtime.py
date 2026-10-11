"""Native publication scope and recorder locks share one cumulative I/O budget."""

from _thread import RLock
from collections.abc import Iterator
from contextlib import contextmanager, nullcontext
from time import monotonic

from agent_core.harness.public_output_lifecycle import PUBLIC_OUTPUT_IO_SECONDS
from agent_storage.postgres.task_io import current_task_io_deadline, task_io_deadline


@contextmanager
def publication_lock(lock: RLock, *, bounded: bool = False) -> Iterator[None]:
    deadline = current_task_io_deadline()
    if deadline is None and bounded:
        deadline = monotonic() + PUBLIC_OUTPUT_IO_SECONDS
    with task_io_deadline(deadline) if deadline is not None else nullcontext():
        if deadline is None:
            lock.acquire()  # Local callers retain their existing non-network lock semantics.
        elif not lock.acquire(timeout=max(0.0, deadline - monotonic())):
            raise TimeoutError("publication mutation lock deadline exceeded")
        try:
            if deadline is not None and monotonic() >= deadline:
                raise TimeoutError("publication mutation lock deadline exceeded")
            yield
        finally:
            lock.release()


@contextmanager
def publication_scope(deadline: float) -> Iterator[float]:
    with task_io_deadline(deadline):
        accepted = current_task_io_deadline()
        assert accepted is not None
        yield accepted
