from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from typing import Any

from agent_core.domain.events import EventType
from agent_core.ports.agent_tasks import TaskEvent


def summarize_task_model_usage(events: Iterable[TaskEvent]) -> dict[str, object] | None:
    """Return the bounded public usage summary for a durable Task."""

    calls: list[Mapping[str, Any]] = [
        item.event.payload
        for item in events
        if item.event.event_type is EventType.MODEL_RESPONSE_RECEIVED
    ]
    if not calls:
        return None
    summary: dict[str, object] = {
        "model_call_count": len(calls),
        "cache_hit_tokens": sum(
            _non_negative(call.get("prompt_cache_hit_tokens")) for call in calls
        ),
        "cache_miss_tokens": sum(
            _non_negative(call.get("prompt_cache_miss_tokens")) for call in calls
        ),
    }
    _copy_latest(summary, calls, "input_tokens")
    _copy_latest(summary, calls, "input_token_limit")
    _copy_latest(summary, calls, "reasoning_effort")
    model = _latest(calls, "resolved_model") or _latest(calls, "model_name")
    if isinstance(model, str) and model.strip():
        summary["model"] = model.strip()
    return summary


def _copy_latest(
    target: dict[str, object], calls: Sequence[Mapping[str, Any]], key: str
) -> None:
    value = _latest(calls, key)
    if isinstance(value, bool):
        return
    if isinstance(value, int | float) and value >= 0:
        target[key] = int(value)
    elif isinstance(value, str) and value.strip():
        target[key] = value.strip()


def _latest(calls: Sequence[Mapping[str, Any]], key: str) -> object | None:
    return next((call[key] for call in reversed(calls) if call.get(key) is not None), None)


def _non_negative(value: object) -> int:
    if isinstance(value, bool) or not isinstance(value, int | float) or value < 0:
        return 0
    return int(value)
