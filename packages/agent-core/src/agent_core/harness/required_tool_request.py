from collections.abc import Mapping
from dataclasses import dataclass

from agent_core.domain.modeling import (
    ModelInvocationPolicy,
    ModelToolChoice,
    ModelToolDefinition,
)
from agent_core.harness.attempt_result import build_attempt_result
from agent_core.harness.models import HarnessAttemptOutcome, HarnessAttemptResult, HarnessEventDraft


def selected_model_tools(
    available: tuple[ModelToolDefinition, ...],
    *,
    allow_tools: bool,
    required_names: tuple[str, ...],
) -> tuple[ModelToolDefinition, ...]:
    tools = available if allow_tools else ()
    if not required_names:
        return tools
    if not allow_tools or len(required_names) != len(set(required_names)):
        raise ValueError("required tool selection must be unique and tool-enabled")
    selected = set(required_names)
    tools = tuple(tool for tool in tools if tool.name in selected)
    if len(tools) != len(selected):
        raise ValueError("required tool selection must be currently advertised")
    return tools


@dataclass(frozen=True)
class EvidenceCorrectionRequest:
    tool_names: tuple[str, ...]
    invocation_policy: ModelInvocationPolicy | None


def evidence_correction_request(
    metadata: dict[str, object],
) -> EvidenceCorrectionRequest:
    value = metadata.pop("required_evidence_tool_names", ())
    names = (
        value
        if isinstance(value, tuple) and all(isinstance(name, str) for name in value)
        else ()
    )
    return EvidenceCorrectionRequest(
        names,
        ModelInvocationPolicy(tool_choice=ModelToolChoice.REQUIRED) if names else None,
    )


def evidence_correction_budget_failure(
    *,
    metadata: Mapping[str, object],
    assistant_message: str,
    model_calls_used: int,
    tool_calls_executed: int,
    emitted_events: list[HarnessEventDraft],
    correction_attempted: bool = False,
) -> HarnessAttemptResult:
    stop_reason = (
        "completion_evidence_missing_after_correction"
        if correction_attempted
        else "completion_evidence_missing"
    )
    return build_attempt_result(
        outcome=HarnessAttemptOutcome.FAILED,
        summary="completion evidence contract is not satisfied",
        assistant_message=assistant_message,
        model_calls_used=model_calls_used,
        tool_calls_executed=tool_calls_executed,
        emitted_events=emitted_events,
        metadata={**metadata, "stop_reason": stop_reason},
    )
