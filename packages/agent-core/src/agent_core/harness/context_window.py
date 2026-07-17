from __future__ import annotations

import json
from dataclasses import dataclass

from agent_core.domain.messages import SessionMessage
from agent_core.domain.modeling import ModelContextWindow, ModelToolDefinition


class ContextWindowExceededError(RuntimeError):
    pass


@dataclass(frozen=True)
class ContextWindowPlan:
    estimated_input_tokens: int
    input_token_limit: int
    within_budget: bool


def plan_context_window(
    messages: tuple[SessionMessage, ...],
    tools: tuple[ModelToolDefinition, ...],
    window: ModelContextWindow,
) -> ContextWindowPlan:
    payload = {
        "messages": [message.model_dump(mode="json") for message in messages],
        "tools": [
            {
                "name": tool.name,
                "description": tool.description,
                "parameters": dict(tool.parameters),
            }
            for tool in tools
        ],
    }
    encoded = json.dumps(payload, separators=(",", ":"), sort_keys=True, ensure_ascii=False)
    estimated = max(1, (len(encoded) + 3) // 4)
    return ContextWindowPlan(
        estimated_input_tokens=estimated,
        input_token_limit=window.input_token_limit,
        within_budget=estimated <= window.input_token_limit,
    )
