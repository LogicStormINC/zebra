"""Publication deadlines and real timer shutdown, without infrastructure imports."""

from _thread import RLock
from collections.abc import Callable, Iterator
from contextlib import AbstractContextManager, contextmanager, nullcontext
from contextvars import ContextVar
from threading import Event, Thread, Timer, current_thread
from time import monotonic

from agent_core.domain.events import EventType

PUBLIC_OUTPUT_IO_SECONDS = 2.0
CANONICAL_EVENT_IO_SECONDS = 5.0
PUBLIC_OUTPUT_CLOSE_SECONDS = 2.5
type PublicationScope = Callable[[float], AbstractContextManager[float]]
_DEADLINE: ContextVar[float | None] = ContextVar("public_output_deadline", default=None)


class PublicOutputClosed(RuntimeError):
    """A callback stopped before admitting any further publication."""


def current_public_output_deadline() -> float | None:
    return _DEADLINE.get()


def _acquire(lock: RLock, deadline: float, closing: Event | None = None) -> None:
    while True:
        if closing is not None and closing.is_set():
            raise PublicOutputClosed("public output is closing")
        remaining = deadline - monotonic()
        if remaining <= 0:
            raise TimeoutError("public output lock deadline exceeded")
        if lock.acquire(timeout=min(0.05, remaining)):
            return


def event_io_seconds(kind: EventType | None) -> float:
    # ponytail: a primary fact includes several bounded DB transactions; the
    # short UI timer budget must not cut off its aggregate commit acknowledgement.
    return (
        PUBLIC_OUTPUT_IO_SECONDS
        if kind is None
        or kind
        in {
            EventType.PUBLIC_OUTPUT,
            EventType.MODEL_RESPONSE_DELTA,
        }
        else CANONICAL_EVENT_IO_SECONDS
    )


@contextmanager
def public_output_lock(
    lock: RLock,
    scope: PublicationScope | None,
    closing: Event | None = None,
    *,
    event_type: EventType | None = None,
) -> Iterator[None]:
    deadline = monotonic() + event_io_seconds(event_type)
    if (current := _DEADLINE.get()) is not None:
        deadline = min(deadline, current)
    with scope(deadline) if scope is not None else nullcontext(deadline) as accepted:
        deadline = min(deadline, accepted)
        token = _DEADLINE.set(deadline)
        try:
            _acquire(lock, deadline, closing)
            try:
                if closing is not None and closing.is_set():
                    raise PublicOutputClosed("public output is closing")
                yield
            finally:
                lock.release()
        finally:
            _DEADLINE.reset(token)


def close_public_output(
    lock: RLock,
    closing: Event,
    timers: Callable[[], tuple[Thread | None, ...]],
    finish: Callable[[], None],
) -> None:
    """Failure retains the owner's references; it is never a successful detach."""
    closing.set()
    deadline = monotonic() + PUBLIC_OUTPUT_CLOSE_SECONDS
    observed = timers()
    for timer in observed:
        if isinstance(timer, Timer):
            timer.cancel()
    _acquire(lock, deadline)
    try:
        observed += timers()
        for timer in observed:
            if isinstance(timer, Timer):
                timer.cancel()
    finally:
        lock.release()
    for timer in observed:
        if timer is not None and timer is not current_thread():
            timer.join(max(0.0, deadline - monotonic()))
            if timer.is_alive():
                raise TimeoutError("public output close failed: timer is still alive")
    _acquire(lock, deadline)
    try:
        finish()
    finally:
        lock.release()
