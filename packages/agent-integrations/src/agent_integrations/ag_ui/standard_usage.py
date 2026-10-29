"""Exact call accounting; cache and reasoning are subsets, never extra tokens."""

from collections.abc import Mapping

from ag_ui.core import CustomEvent, TokenUsage

from agent_integrations.ag_ui.contracts import AgUiProjectionError
from agent_integrations.ag_ui.standard_state import StandardProjectionState

_FIELDS = {
    "input_tokens": "input_tokens",
    "output_tokens": "output_tokens",
    "total_tokens": "total_tokens",
    "reasoning_tokens": "reasoning_tokens",
    "prompt_cache_hit_tokens": "cached_input_tokens",
    "cache_write_input_tokens": "cache_write_input_tokens",
}


def record_usage(
    payload: Mapping[str, object],
    state: StandardProjectionState,
    timestamp: int,
    *,
    fallback_call_id: str | None = None,
) -> tuple[CustomEvent, ...]:
    actual_call = payload.get("model_call_id")
    if actual_call is not None and (not isinstance(actual_call, str) or not actual_call.strip()):
        raise AgUiProjectionError("usage model_call_id must be nonblank text when present")
    call = (
        actual_call
        if isinstance(actual_call, str) and actual_call.strip()
        else ("event:" + fallback_call_id if fallback_call_id is not None else None)
    )
    if call is None:
        state.usage_unknown = True
        return ()
    if call in state.seen_usage:
        return ()
    values: dict[str, int | str] = {}
    for source, target in _FIELDS.items():
        count = payload.get(source)
        if count is None:
            continue
        if type(count) is not int or not 0 <= count <= 9_007_199_254_740_991:
            raise AgUiProjectionError("usage counts must be nonnegative safe integers")
        values[target] = count
    if "input_tokens" in values and "output_tokens" in values:
        values["total_tokens"] = int(values["input_tokens"]) + int(values["output_tokens"])
    for subset, total in (
        ("reasoning_tokens", "output_tokens"),
        ("cached_input_tokens", "input_tokens"),
        ("cache_write_input_tokens", "input_tokens"),
    ):
        if subset in values and total in values and int(values[subset]) > int(values[total]):
            raise AgUiProjectionError("usage subset exceeds its total")
    if "input_tokens" in values and sum(
        int(values.get(k, 0)) for k in ("cached_input_tokens", "cache_write_input_tokens")
    ) > int(values["input_tokens"]):
        raise AgUiProjectionError("usage cache subsets exceed input total")
    if "total_tokens" in values and any(
        int(values["total_tokens"]) < int(values.get(key, 0))
        for key in ("input_tokens", "output_tokens")
    ):
        raise AgUiProjectionError("usage total is smaller than a known component")
    reported = bool(values)
    for source, target in (("provider", "provider"), ("resolved_model", "model")):
        label = payload.get(source)
        if isinstance(label, str) and label.strip():
            values[target] = label
    if not reported and not all(key in values for key in ("provider", "model")):
        state.usage_unknown = True
    usage = TokenUsage.model_validate(values).model_dump(
        mode="json", by_alias=True, exclude_none=True
    )
    state.seen_usage.add(call)
    previous = next(
        (
            row
            for row in state.usage
            if all(row.get(label) == usage.get(label) for label in ("provider", "model"))
        ),
        None,
    )
    if previous is None:
        state.usage.append(dict(usage))
    else:
        # Unknown counts stay unknown if any call lacks that count.
        for key in tuple(previous):
            if key in {"provider", "model"}:
                continue
            if key not in usage:
                previous.pop(key)
            else:
                previous[key] += usage[key]
        TokenUsage.model_validate(previous)
    if not reported:
        return ()
    return (
        CustomEvent(
            timestamp=timestamp,
            name="zebra.model_usage.v1",
            value={
                "scope": "model_call",
                "model_call_id": actual_call,
                "usage": usage,
            },
        ),
    )


def terminal_usage(state: StandardProjectionState) -> list[TokenUsage] | None:
    """Inclusive totals are unknown if any represented child lacks durable token facts."""
    if state.usage_unknown or state.subagent_usage_unknown:
        return None
    return [TokenUsage.model_validate(row) for row in state.usage] or None
