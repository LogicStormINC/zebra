"""Independent command-lane polling cadence and credential-safe diagnostics."""

import asyncio
import logging
from collections.abc import Awaitable, Callable

from agent_runtime.command_wakeup_consumer import PickupOutcome

from zebra_agent_worker.worker_polling import PollingDelay, PollingState

logger = logging.getLogger(__name__)


def safe_trace(exc: Exception) -> str:
    """Keep actionable frame locations without logging source lines or values."""
    frames: list[str] = []
    traceback = exc.__traceback__
    while traceback is not None:
        code = traceback.tb_frame.f_code
        frames.append(f"{code.co_filename.rsplit('/', 1)[-1]}:{traceback.tb_lineno}:{code.co_name}")
        traceback = traceback.tb_next
    return " <- ".join(frames[-8:]) or "unavailable"


def outcome_state(outcomes: tuple[PickupOutcome, ...]) -> PollingState:
    if any(value != PickupOutcome.DEFERRED for value in outcomes):
        return "progress"
    return "blocked" if outcomes else "idle"


async def background(
    action: Callable[[], Awaitable[object]], *, stop: asyncio.Event, interval: float,
) -> None:
    delay = PollingDelay(interval)
    while not stop.is_set():
        try:
            result = await action()
        except Exception as exc:
            logger.warning("command_background_tick_failed error_type=%s trace=%s",
                           type(exc).__name__, safe_trace(exc))
            state: PollingState = "error"
        else:
            state = outcome_state(result) if isinstance(result, tuple) else "progress"
        try:
            await asyncio.wait_for(stop.wait(), delay.next(state))
        except TimeoutError:
            pass
