from __future__ import annotations

import json
from collections.abc import Callable, Mapping
from dataclasses import dataclass

from agent_core.domain.messages import MessageRole, SessionMessage
from agent_core.domain.modeling import (
    CONTEXT_TOKEN_CATEGORIES,
    ModelContextWindow,
    ModelTokenBreakdown,
    ModelToolDefinition,
    ModelToolOrigin,
)


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
    token_breakdown_v2: ModelTokenBreakdown | None = None
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
    tool_payloads: list[dict[str, object]] = [
        {"name": tool.name, "description": tool.description, "parameters": dict(tool.parameters)}
        for tool in tools
    ]
    breakdown = {
        "system": _estimate([value for value in message_payloads if value["role"] == "system"]),
        "messages": _estimate([value for value in message_payloads if value["role"] != "system"]),
        "tools": _estimate(tool_payloads) if tool_payloads else 0,
    }
    categorized_messages: dict[str, list[dict[str, object]]] = {
        "messages": [],
        "skills": [],
        "system_prompt": [],
    }
    for message, payload in zip(messages, message_payloads, strict=True):
        categorized_messages[_message_category(message)].append(payload)
    detailed = {
        "messages": _estimate_items(categorized_messages["messages"]),
        "system_tools": _estimate_items(
            [payload for tool, payload in zip(tools, tool_payloads, strict=True)
             if tool.origin is not ModelToolOrigin.MCP]
        ),
        "skills": _estimate_items(categorized_messages["skills"]),
        "system_prompt": _estimate_items(categorized_messages["system_prompt"]),
        "mcp_tools": _estimate_items(
            [payload for tool, payload in zip(tools, tool_payloads, strict=True)
             if tool.origin is ModelToolOrigin.MCP]
        ),
        "other": 0,
    }
    estimated = (
        token_counter(messages, tools)
        if token_counter is not None
        else _estimate({"messages": message_payloads, "tools": tool_payloads})
    )
    if estimated < 0:
        raise ValueError("provider token count must not be negative")
    estimate_method = "provider" if token_counter is not None else "chars_div_4"
    return ContextWindowPlan(
        estimated_input_tokens=estimated,
        input_token_limit=window.input_token_limit,
        within_budget=estimated <= window.input_token_limit,
        compact_at=window.compact_at,
        profile_name=window.profile_name,
        estimate_method=estimate_method,
        token_breakdown=breakdown,
        token_breakdown_v2=_reconcile_breakdown(
            detailed,
            estimated,
            basis="provider_estimated" if token_counter is not None else "chars_div_4",
            estimate_method=estimate_method,
        ),
        attempted_strategies=attempted_strategies,
    )


def reconcile_context_breakdown(
    plan: ContextWindowPlan,
    provider_input_tokens: int | None,
) -> ModelTokenBreakdown:
    if plan.token_breakdown_v2 is None:
        legacy = {
            "messages": plan.token_breakdown.get("messages", 0),
            "system_tools": plan.token_breakdown.get("tools", 0),
            "skills": 0,
            "system_prompt": plan.token_breakdown.get("system", 0),
            "mcp_tools": 0,
            "other": 0,
        }
        return _reconcile_breakdown(
            legacy,
            plan.estimated_input_tokens if provider_input_tokens is None else provider_input_tokens,
            basis=(
                "legacy_estimated"
                if provider_input_tokens is None
                else "reconciled_provider_total"
            ),
            estimate_method=plan.estimate_method,
            provider_input_tokens=provider_input_tokens,
            estimate_error=(
                None
                if provider_input_tokens is None
                else provider_input_tokens - plan.estimated_input_tokens
            ),
        )
    if provider_input_tokens is None:
        return plan.token_breakdown_v2
    return _reconcile_breakdown(
        plan.token_breakdown_v2.categories,
        provider_input_tokens,
        basis="reconciled_provider_total",
        estimate_method=plan.estimate_method,
        raw_estimated_total=plan.token_breakdown_v2.raw_estimated_total,
        provider_input_tokens=provider_input_tokens,
        estimate_error=provider_input_tokens - plan.estimated_input_tokens,
    )


def context_breakdown_v2_payload(plan: ContextWindowPlan) -> dict[str, object]:
    if plan.token_breakdown_v2 is None:
        return {}
    return {"token_breakdown_v2": plan.token_breakdown_v2.as_payload()}


def _message_category(message: SessionMessage) -> str:
    segment = message.metadata.get("context_segment")
    if segment == "skills":
        return "skills"
    return "system_prompt" if message.role is MessageRole.SYSTEM else "messages"


def _estimate_items(values: list[dict[str, object]]) -> int:
    return _estimate(values) if values else 0


def _reconcile_breakdown(
    values: Mapping[str, int],
    target_total: int,
    *,
    basis: str,
    estimate_method: str,
    raw_estimated_total: int | None = None,
    provider_input_tokens: int | None = None,
    estimate_error: int | None = None,
) -> ModelTokenBreakdown:
    raw = {key: max(0, int(values.get(key, 0))) for key in CONTEXT_TOKEN_CATEGORIES}
    raw_total = sum(raw.values())
    reconciled = dict.fromkeys(CONTEXT_TOKEN_CATEGORIES, 0)
    if target_total and raw_total:
        remainders: list[tuple[int, int, str]] = []
        for index, key in enumerate(CONTEXT_TOKEN_CATEGORIES):
            numerator = target_total * raw[key]
            reconciled[key] = numerator // raw_total
            remainders.append((numerator % raw_total, -index, key))
        remaining = target_total - sum(reconciled.values())
        for _, _, key in sorted(remainders, reverse=True)[:remaining]:
            reconciled[key] += 1
    elif target_total:
        reconciled["other"] = target_total
    return ModelTokenBreakdown(
        categories=reconciled,
        basis=basis,
        estimate_method=estimate_method,
        raw_estimated_total=raw_total if raw_estimated_total is None else raw_estimated_total,
        provider_input_tokens=provider_input_tokens,
        estimate_error=estimate_error,
    )


def _estimate(value: object) -> int:
    encoded = json.dumps(value, separators=(",", ":"), sort_keys=True, ensure_ascii=False)
    return max(1, (len(encoded) + 3) // 4)
