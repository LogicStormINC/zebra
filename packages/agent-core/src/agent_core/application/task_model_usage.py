"""Incremental equivalent of the public Task model usage projection."""

from collections.abc import Mapping
from typing import Any

from agent_core.contracts.model_events import ModelTokenBreakdownV2Payload

LATEST_USAGE_KEYS = (
    "input_tokens",
    "input_token_limit",
    "reasoning_effort",
    "token_breakdown",
    "token_breakdown_v2",
    "resolved_model",
    "model_name",
)


def advance_model_usage(state: Mapping[str, Any], payload: Mapping[str, Any]) -> dict[str, Any]:
    latest = dict(state.get("latest", {}))
    latest.update({key: payload[key] for key in LATEST_USAGE_KEYS if payload.get(key) is not None})
    return {
        "model_call_count": state.get("model_call_count", 0) + 1,
        "cache_hit_tokens": state.get("cache_hit_tokens", 0)
        + _non_negative(payload.get("prompt_cache_hit_tokens")),
        "cache_miss_tokens": state.get("cache_miss_tokens", 0)
        + _non_negative(payload.get("prompt_cache_miss_tokens")),
        "latest": latest,
    }


def public_model_usage(state: Mapping[str, Any]) -> dict[str, object] | None:
    if not state.get("model_call_count"):
        return None
    summary: dict[str, object] = {
        key: state[key] for key in ("model_call_count", "cache_hit_tokens", "cache_miss_tokens")
    }
    latest = state["latest"]
    for key in ("input_tokens", "input_token_limit", "reasoning_effort"):
        value = latest.get(key)
        if isinstance(value, bool):
            continue
        if isinstance(value, int | float) and value >= 0:
            summary[key] = int(value)
        elif isinstance(value, str) and value.strip():
            summary[key] = value.strip()
    breakdown = latest.get("token_breakdown")
    if isinstance(breakdown, Mapping):
        bounded = {
            key: _non_negative(breakdown.get(key))
            for key in ("messages", "system", "tools")
            if breakdown.get(key) is not None
        }
        if bounded:
            summary["token_breakdown"] = bounded
    try:
        detailed = ModelTokenBreakdownV2Payload.model_validate(latest.get("token_breakdown_v2"))
    except (TypeError, ValueError):
        pass
    else:
        summary["token_breakdown_v2"] = detailed.model_dump(mode="json", exclude_none=True)
    model = latest.get("resolved_model") or latest.get("model_name")
    if isinstance(model, str) and model.strip():
        summary["model"] = model.strip()
    return summary


def _non_negative(value: object) -> int:
    if isinstance(value, bool) or not isinstance(value, int | float) or value < 0:
        return 0
    return int(value)
