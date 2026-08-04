from agent_core.domain.events import EventActor, EventType
from agent_core.domain.messages import SessionMessage
from agent_core.domain.modeling import ModelCompletion
from agent_core.domain.policies import PolicyDecision
from agent_core.domain.tools import ToolCall
from agent_core.harness.models import HarnessEventDraft
from agent_core.ports.conversation_compactor import ConversationCompactionResult


def model_response_event(
    completion: ModelCompletion,
    *,
    attempt_number: int,
    response_stage: str | None = None,
) -> HarnessEventDraft:
    payload: dict[str, object] = {
        "attempt_number": attempt_number,
        "assistant_message": completion.assistant_message.content,
        "tool_call_count": len(completion.tool_calls),
        "provider": completion.call_metadata.provider,
        "model_name": completion.call_metadata.model_name,
        "input_tokens": completion.call_metadata.usage.input_tokens,
        "output_tokens": completion.call_metadata.usage.output_tokens,
        "total_tokens": completion.call_metadata.usage.total_tokens,
        "reasoning_tokens": completion.call_metadata.usage.reasoning_tokens,
        "prompt_cache_hit_tokens": (completion.call_metadata.usage.prompt_cache_hit_tokens),
        "prompt_cache_miss_tokens": (completion.call_metadata.usage.prompt_cache_miss_tokens),
        "latency_ms": completion.call_metadata.latency_ms,
        "time_to_first_event_ms": completion.call_metadata.time_to_first_event_ms,
        "time_to_first_public_text_ms": (completion.call_metadata.time_to_first_public_text_ms),
        "cache_hit": completion.call_metadata.cache_hit,
        "cost_usd": completion.call_metadata.cost_usd,
        "profile_id": completion.call_metadata.profile_id,
        "profile_version_observed_at": (completion.call_metadata.profile_version_observed_at),
        "requested_model": completion.call_metadata.requested_model,
        "resolved_model": completion.call_metadata.resolved_model,
        "role": completion.call_metadata.role,
        "thinking_mode": completion.call_metadata.thinking_mode,
        "reasoning_effort": completion.call_metadata.reasoning_effort,
        "tool_choice": completion.call_metadata.tool_choice,
        "prompt_version": completion.call_metadata.prompt_version,
        "tool_schema_bytes": completion.call_metadata.tool_schema_bytes,
        "tool_schema_hash": completion.call_metadata.tool_schema_hash,
        "stable_prefix_hash": completion.call_metadata.stable_prefix_hash,
        "finish_reason": completion.call_metadata.finish_reason,
        "system_fingerprint": completion.call_metadata.system_fingerprint,
        "retry_count": completion.call_metadata.retry_count,
        "response_repair_count": completion.call_metadata.response_repair_count,
        "normalized_error": completion.call_metadata.normalized_error,
    }
    if completion.call_metadata.model_call_id is not None:
        payload["model_call_id"] = completion.call_metadata.model_call_id
    if completion.output_contract is not None:
        payload["output_contract"] = dict(completion.output_contract)
    if completion.call_metadata.estimated_input_tokens is not None:
        estimated = completion.call_metadata.estimated_input_tokens
        payload["estimated_input_tokens"] = estimated
        payload["input_token_limit"] = completion.call_metadata.input_token_limit
        payload["token_estimate_method"] = completion.call_metadata.token_estimate_method
        if completion.call_metadata.usage.input_tokens is not None:
            payload["input_token_estimate_error"] = (
                completion.call_metadata.usage.input_tokens - estimated
            )
    if response_stage is not None:
        payload["response_stage"] = response_stage
    return HarnessEventDraft(
        event_type=EventType.MODEL_RESPONSE_RECEIVED,
        actor=EventActor.HARNESS,
        payload=payload,
    )


def context_compacted_event(
    result: ConversationCompactionResult,
    *,
    attempt_number: int,
) -> HarnessEventDraft:
    payload: dict[str, object] = {
        "attempt_number": attempt_number,
        "before_tokens": result.before_tokens,
        "after_tokens": result.after_tokens,
        "removed_message_count": result.removed_message_count,
        "retained_message_count": result.retained_message_count,
        "within_budget": result.within_budget,
        "provenance": result.provenance,
    }
    if result.capsule is not None:
        payload["capsule"] = result.capsule.model_dump(mode="json")
    return HarnessEventDraft(
        event_type=EventType.CONTEXT_COMPACTED,
        actor=EventActor.HARNESS,
        payload=payload,
    )


def policy_decision_payload(
    *,
    attempt_number: int,
    tool_call: ToolCall,
    decision: PolicyDecision,
) -> dict[str, object]:
    payload: dict[str, object] = {
        "attempt_number": attempt_number,
        "decision": decision.decision.value,
        "reason": decision.reason,
        "policy_profile": decision.policy_profile,
        "tool_name": tool_call.name,
        "tool_call_id": str(tool_call.tool_call_id),
    }
    _extend_proxy_policy_payload(payload, decision)
    return payload


def approval_requested_payload(
    *,
    attempt_number: int,
    tool_call: ToolCall,
    assistant_message: str,
    decision: PolicyDecision,
    conversation: list[SessionMessage],
    model_calls_used: int,
    tool_calls_executed: int,
    remaining_tool_calls: tuple[ToolCall, ...] = (),
) -> dict[str, object]:
    payload: dict[str, object] = {
        "attempt_number": attempt_number,
        "reason": decision.reason,
        "policy_profile": decision.policy_profile,
        "tool_name": tool_call.name,
        "arguments": tool_call.arguments,
        "tool_call_id": str(tool_call.tool_call_id),
        "assistant_message": assistant_message,
        "call_fingerprint": tool_call.approval_fingerprint,
    }
    if tool_calls_executed or remaining_tool_calls:
        payload["conversation"] = [message.model_dump(mode="json") for message in conversation]
        payload["model_calls_used"] = model_calls_used
        payload["tool_calls_executed"] = tool_calls_executed
    if remaining_tool_calls:
        payload["remaining_tool_calls"] = [
            call.model_dump(mode="json") for call in remaining_tool_calls
        ]
    if tool_call.provider_call_id is not None:
        payload["provider_call_id"] = tool_call.provider_call_id
    if tool_call.provider_tool_name is not None:
        payload["provider_tool_name"] = tool_call.provider_tool_name
        payload["provider_arguments"] = tool_call.provider_arguments or {}
    _extend_proxy_policy_payload(payload, decision)
    return payload


def _extend_proxy_policy_payload(
    payload: dict[str, object],
    decision: PolicyDecision,
) -> None:
    if decision.route is not None:
        payload["route"] = decision.route
    if decision.target is not None:
        payload["target"] = decision.target
    if decision.network_profile is not None:
        payload["network_profile"] = decision.network_profile
    if decision.scope:
        payload["scope"] = list(decision.scope)
