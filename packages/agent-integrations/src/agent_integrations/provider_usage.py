"""Observe individual provider attempts without retaining request or response bodies."""

from collections.abc import Callable
from typing import Any, Literal
from uuid import UUID, uuid4

from agent_core.domain.modeling import ModelUsage

ProviderUsageObserver = Callable[[UUID, Literal["started", "finished"], ModelUsage | None], None]


def observe_provider_attempt(
    observer: ProviderUsageObserver | None,
    send: Callable[[], dict[str, Any]],
    parse_usage: Callable[[object], ModelUsage],
) -> dict[str, Any]:
    if observer is None:
        return send()
    attempt = uuid4()
    observer(attempt, "started", None)
    usage = None
    try:
        payload = send()
        try:
            usage = parse_usage(payload.get("usage"))
        except ValueError:
            pass
        return payload
    finally:
        observer(attempt, "finished", usage)
