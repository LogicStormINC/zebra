"""Small deterministic rules for the Worker polling fallback."""

from typing import Protocol


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
    if idle_sleep_seconds < 0:
        raise ValueError("idle_sleep_seconds must not be negative")
