"""Shared Worker polling bounds and command cadence validation."""

import math
from random import uniform
from typing import Literal, Protocol

PollingState = Literal["progress", "idle", "blocked", "error"]


class PollingDelay:
    """Back off discovery only; this never retries an execution or control intent."""

    def __init__(self, base: float) -> None:
        if type(base) not in (int, float) or not math.isfinite(base) or base < 0:
            raise ValueError("worker idle interval must be finite and non-negative")
        self._base = base
        self._state: PollingState = "progress"
        self._streak = 0

    def next(self, state: PollingState) -> float:
        if state not in ("progress", "idle", "blocked", "error"):
            raise ValueError("invalid worker polling state")
        self._streak = 0 if state == "progress" or state != self._state else self._streak
        self._state = state
        if state == "progress":
            return self._base
        self._streak = min(16, self._streak + 1)
        # ponytail: one local streak per lane, not a second scheduler. Keep idle/
        # blocked discovery <=1s at normal cadence; errors <=5s. Explicit slower
        # operator cadence stays authoritative; capacity/SLO proof belongs to03B.
        ceiling = min(max(self._base, 5 if state == "error" else 1),
                      max(0.05, self._base) * 2 ** self._streak)
        return uniform(max(0.05, self._base, ceiling * 0.8), ceiling)


class CycleAccumulator(Protocol):
    cycles_completed: int


def has_remaining_cycles(accumulator: CycleAccumulator, max_cycles: int | None) -> bool:
    return max_cycles is None or accumulator.cycles_completed < max_cycles


def validate_loop_inputs(
    *,
    batch_size: int,
    lease_ttl_seconds: int,
    max_cycles: int | None,
    idle_sleep_seconds: float,
) -> None:
    if batch_size <= 0:
        raise ValueError("batch_size must be greater than zero")
    if lease_ttl_seconds <= 0:
        raise ValueError("lease_ttl_seconds must be greater than zero")
    if max_cycles is not None and max_cycles <= 0:
        raise ValueError("max_cycles must be greater than zero when provided")
    if (type(idle_sleep_seconds) not in (int, float)
        or not math.isfinite(idle_sleep_seconds) or idle_sleep_seconds < 0):
        raise ValueError("idle_sleep_seconds must be finite and non-negative")


def validate_command_cadence(
    *, batch_size: int, idle_sleep_seconds: float, command_batch_limit: int,
) -> None:
    if type(batch_size) is not int or batch_size > command_batch_limit:
        raise ValueError("worker batch exceeds configured command batch limit")
    if (
        type(idle_sleep_seconds) not in (int, float)
        or not math.isfinite(idle_sleep_seconds)
        or not 0 <= idle_sleep_seconds <= 30
    ):
        raise ValueError("worker idle interval is outside bounds")
