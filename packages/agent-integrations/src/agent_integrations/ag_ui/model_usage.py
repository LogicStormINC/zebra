from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from ag_ui.core import CustomEvent


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
    if not value:
        return None
    return CustomEvent(timestamp=timestamp, name="zebra.model_usage", value=value)
