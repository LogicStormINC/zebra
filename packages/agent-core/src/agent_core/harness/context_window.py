from __future__ import annotations

import json
from collections.abc import Callable
from dataclasses import dataclass

from agent_core.domain.messages import SessionMessage
from agent_core.domain.modeling import ModelContextWindow, ModelToolDefinition


class ContextWindowExceededError(RuntimeError):
    def __init__(self, plan: ContextWindowPlan) -> None:
        self.plan = plan
        largest = max(plan.token_breakdown, key=lambda key: plan.token_breakdown[key])
        super().__init__(
            "model request exceeds input budget: "
            f"{plan.estimated_input_tokens}>{plan.input_token_limit}; "
            f"largest={largest}:{plan.token_breakdown[largest]}; "
            f"attempted={','.join(plan.attempted_strategies) or 'hard-gate'}"
        )


@dataclass(frozen=True)
class ContextWindowPlan:
    estimated_input_tokens: int
    input_token_limit: int
    within_budget: bool
    compact_at: int
    profile_name: str
    estimate_method: str
    token_breakdown: dict[str, int]
    attempted_strategies: tuple[str, ...] = ()


def plan_context_window(
    messages: tuple[SessionMessage, ...],
    tools: tuple[ModelToolDefinition, ...],
    window: ModelContextWindow,
    *,
    token_counter: Callable[[tuple[SessionMessage, ...], tuple[ModelToolDefinition, ...]], int]
    | None = None,
    attempted_strategies: tuple[str, ...] = (),
) -> ContextWindowPlan:
    message_payloads = [message.model_dump(mode="json") for message in messages]
    tool_payloads = [
        {"name": tool.name, "description": tool.description, "parameters": dict(tool.parameters)}
        for tool in tools
    ]
    breakdown = {
        "system": _estimate([value for value in message_payloads if value["role"] == "system"]),
        "messages": _estimate([value for value in message_payloads if value["role"] != "system"]),
        "tools": _estimate(tool_payloads) if tool_payloads else 0,
    }
    estimated = (
        token_counter(messages, tools)
        if token_counter is not None
        else _estimate({"messages": message_payloads, "tools": tool_payloads})
    )
    if estimated < 0:
        raise ValueError("provider token count must not be negative")
    return ContextWindowPlan(
        estimated_input_tokens=estimated,
        input_token_limit=window.input_token_limit,
        within_budget=estimated <= window.input_token_limit,
        compact_at=window.compact_at,
        profile_name=window.profile_name,
        estimate_method="provider" if token_counter is not None else "chars_div_4",
        token_breakdown=breakdown,
        attempted_strategies=attempted_strategies,
    )


def _estimate(value: object) -> int:
    encoded = json.dumps(value, separators=(",", ":"), sort_keys=True, ensure_ascii=False)
    return max(1, (len(encoded) + 3) // 4)
