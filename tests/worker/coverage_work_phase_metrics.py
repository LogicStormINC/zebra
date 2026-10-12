"""Observe native code frames without replacing security-qualified delegates."""

import sys
from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import ContextVar, Token
from time import perf_counter
from types import FrameType
from typing import Any


@contextmanager
def observe_phases(
    targets: tuple[tuple[type[Any], str], ...],
    phase: ContextVar[str],
    cost: dict[str, Any],
    *, counts_only: tuple[tuple[type[Any], str], ...] = (),
) -> Iterator[None]:
    codes = {getattr(kind, name).__code__: f"{kind.__name__}.{name}" for kind, name in targets}
    counted = {getattr(kind, name).__code__: f"{kind.__name__}.{name}"
               for kind, name in counts_only}
    active: dict[int, tuple[str, float, Token[str] | None]] = {}
    previous = sys.getprofile()

    def observe(frame: FrameType, event: str, argument: Any) -> None:
        label = codes.get(frame.f_code, counted.get(frame.f_code))
        if label is not None:
            identity = id(frame)
            if event == "call":
                active[identity] = (
                    label, perf_counter(), phase.set(label) if frame.f_code in codes else None,
                )
            elif event == "return":
                entry = active.pop(identity, None)
                if entry is not None:
                    name, stamp, token = entry
                    if token is not None:
                        phase.reset(token)
                    cost[name]["calls"] += 1
                    cost[name]["seconds"] += perf_counter() - stamp
                    if type(argument) is bool:
                        outcome = "true_results" if argument else "false_results"
                        cost[name][outcome] = cost[name].get(outcome, 0) + 1
        if previous is not None:
            previous(frame, event, argument)

    sys.setprofile(observe)
    try:
        yield
    finally:
        sys.setprofile(previous)
        active.clear()
