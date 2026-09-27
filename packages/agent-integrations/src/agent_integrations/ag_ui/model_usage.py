from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from ag_ui.core import CustomEvent
from agent_core.contracts.model_events import ModelTokenBreakdownV2Payload


def project_model_usage(payload: Mapping[str, Any], *, timestamp: int) -> CustomEvent | None:
    value = {
        key: payload[key]
        for key in (
            "input_tokens",
            "input_token_limit",
            "prompt_cache_hit_tokens",
            "prompt_cache_miss_tokens",
            "model_name",
            "resolved_model",
            "reasoning_effort",
        )
        if key in payload and payload[key] is not None
    }
    breakdown = payload.get("token_breakdown")
    if isinstance(breakdown, Mapping):
        bounded = {
            key: int(item)
            for key in ("messages", "system", "tools")
            if not isinstance((item := breakdown.get(key)), bool)
            and isinstance(item, int | float)
            and item >= 0
        }
        if bounded:
            value["token_breakdown"] = bounded
    try:
        detailed = ModelTokenBreakdownV2Payload.model_validate(
            payload.get("token_breakdown_v2")
        )
    except (TypeError, ValueError):
        detailed = None
    if detailed is not None:
        value["token_breakdown_v2"] = detailed.model_dump(
            mode="json", exclude_none=True
        )
    if not value:
        return None
    return CustomEvent(timestamp=timestamp, name="zebra.model_usage", value=value)
