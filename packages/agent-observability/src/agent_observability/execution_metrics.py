from __future__ import annotations

import math
from collections import defaultdict, deque
from dataclasses import dataclass

from agent_core.domain.events import EventType, SessionEvent

_STAGE_EVENTS = {
    "preparation": (
        frozenset({EventType.HARNESS_ATTEMPT_STARTED}),
        frozenset({EventType.MODEL_REQUEST_STARTED}),
    ),
    "queue_wait": (
        frozenset({EventType.SESSION_COMMAND_ACCEPTED}),
        frozenset({EventType.HARNESS_ATTEMPT_STARTED}),
    ),
    "model": (
        frozenset({EventType.MODEL_REQUEST_STARTED}),
        frozenset({EventType.MODEL_RESPONSE_RECEIVED}),
    ),
    "tool": (
        frozenset({EventType.TOOL_EXECUTION_STARTED}),
        frozenset({EventType.TOOL_EXECUTION_COMPLETED, EventType.TOOL_EXECUTION_FAILED}),
    ),
    "client_wait": (
        frozenset({EventType.CLIENT_EFFECT_SCHEDULED}),
        frozenset({EventType.CLIENT_EFFECT_RECEIPT_ACCEPTED}),
    ),
    "turn": (
        frozenset({EventType.HARNESS_ATTEMPT_STARTED}),
        frozenset(
            {EventType.TURN_COMPLETED, EventType.TURN_FAILED, EventType.TURN_CANCELLED}
        ),
    ),
}


@dataclass(frozen=True, slots=True)
class StageLatencySummary:
    stage: str
    observations: int
    incomplete: int
    p50_ms: int | None
    p95_ms: int | None
    maximum_ms: int | None


def summarize_execution_latencies(
    events: tuple[SessionEvent, ...],
) -> tuple[StageLatencySummary, ...]:
    """Project low-cardinality timings without identity labels or payloads."""

    ordered = sorted(events, key=lambda event: event.sequence)
    starts: dict[tuple[str, str, str], deque[SessionEvent]] = defaultdict(deque)
    durations: dict[str, list[int]] = defaultdict(list)
    for event in ordered:
        for stage, (start_types, end_types) in _STAGE_EVENTS.items():
            identity_key = {
                "model": "model_call_id", "tool": "tool_call_id",
                "client_wait": "client_effect_id",
            }.get(stage)
            identity = event.payload.get(identity_key, "") if identity_key else ""
            key = (stage, str(event.session_id), str(identity))
            if event.event_type in start_types:
                starts[key].append(event)
            elif event.event_type in end_types and starts[key]:
                started = starts[key].popleft()
                elapsed = max(
                    0,
                    int((event.created_at - started.created_at).total_seconds() * 1000),
                )
                durations[stage].append(elapsed)
    return tuple(
        _summary(stage, durations[stage], sum(
            len(pending) for key, pending in starts.items() if key[0] == stage
        )) for stage in _STAGE_EVENTS
    )


def _summary(stage: str, values: list[int], incomplete: int) -> StageLatencySummary:
    ordered = sorted(values)
    return StageLatencySummary(
        stage=stage,
        observations=len(ordered),
        incomplete=incomplete,
        p50_ms=_percentile(ordered, 50),
        p95_ms=_percentile(ordered, 95),
        maximum_ms=ordered[-1] if ordered else None,
    )


def _percentile(values: list[int], percentile: int) -> int | None:
    if not values:
        return None
    return values[math.ceil(len(values) * percentile / 100) - 1]
