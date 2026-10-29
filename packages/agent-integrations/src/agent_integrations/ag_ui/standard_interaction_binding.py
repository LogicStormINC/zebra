"""Bounded native human receipt provenance; no private conversation projection."""

from datetime import datetime
from hashlib import sha256
from re import fullmatch
from uuid import UUID

from agent_core.contracts.session_commands import validate_accepted_session_command
from agent_core.domain.client_preparation import ClientPreparationContext
from agent_core.domain.events import EventActor, EventType, SessionEvent
from agent_core.domain.identifiers import ToolCallId
from agent_core.domain.tools import ToolResult
from agent_core.harness.clarification_step import clarification_tool_result

from agent_integrations.ag_ui.contracts import AgUiProjectionError, AgUiRunIdentity
from agent_integrations.ag_ui.standard_interaction_state import InteractionProjectionState


def bind_native_message(
    event: SessionEvent,
    identity: AgUiRunIdentity,
    state: InteractionProjectionState,
    *,
    projection_version: str,
) -> None:
    if (
        event.event_type is not EventType.SESSION_COMMAND_ACCEPTED
        or event.payload.get("kind") != "message"
    ):
        return
    payload = event.payload.get("payload")
    metadata = payload.get("client_preparation") if isinstance(payload, dict) else None
    if not isinstance(metadata, dict):
        return
    command = validate_accepted_session_command(
        event.payload, session_id=event.session_id, idempotency_key=event.idempotency_key
    )
    context = ClientPreparationContext.model_validate(
        {**metadata, "input": command.payload.get("input")}
    )
    if (
        event.actor is not EventActor.USER
        or event.idempotency_key != "agui-interaction:" + str(context.operation_id)
        or str(context.task_id) != identity.thread_id
        or context.run_id != identity.run_id
        or command.payload.get("run_id") != context.run_id
        or fullmatch(r"agui:[0-9a-f]{64}", context.previous_run_id) is None
    ):
        raise AgUiProjectionError("human preparation is not an exact native message")
    if context.projection_version == projection_version and state.previous_protocol_run_id is None:
        state.previous_protocol_run_id = context.previous_run_id
    call, content = command.payload.get("clarification_id"), command.payload.get("content")
    if not isinstance(call, str) or not isinstance(content, str) or not content.strip():
        raise AgUiProjectionError("human preparation lacks its native clarification")
    UUID(call)
    state.pending_clarification = {
        "operation_id": str(context.operation_id),
        "clarification_id": call,
        "content_hash": sha256(content.strip().encode()).hexdigest(),
        "source_event_id": str(event.event_id),
    }


def native_clarification_result(
    event: SessionEvent,
    state: InteractionProjectionState,
) -> ToolResult:
    pending, content = state.pending_clarification, event.payload.get("content")
    if (
        not pending
        or event.actor is not EventActor.USER
        or event.idempotency_key != "agui-interaction:" + pending["operation_id"] + ":message"
        or event.payload.get("clarification_id") != pending["clarification_id"]
        or not isinstance(content, str)
        or sha256(content.encode()).hexdigest() != pending["content_hash"]
    ):
        raise AgUiProjectionError("clarification response lacks its original native message")
    call = pending["clarification_id"]
    state.pending_clarification.clear()
    return clarification_tool_result(ToolCallId(UUID(call)), call, content)


def native_expired_effect(event: SessionEvent, state: InteractionProjectionState) -> dict[str, str]:
    """Only the native recovery command can acknowledge an unconfirmed deadline."""
    command = validate_accepted_session_command(
        event.payload, session_id=event.session_id, idempotency_key=event.idempotency_key
    )
    result = command.payload.get("client_effect_result")
    if not isinstance(result, dict):
        raise AgUiProjectionError("expiry continuation lacks a native result")
    effect_id = result.get("client_effect_id")
    effect = state.pending_effects.get(str(effect_id))
    if (
        not effect
        or state.accepted_receipt
        or event.actor is not EventActor.HARNESS
        or event.idempotency_key != "client-effect-resume:recovery:" + str(effect_id)
        or command.payload != {"client_effect_result": result}
        or result.get("status") != "expired"
        or result.get("result") != {"reason": "browser_action_deadline_exceeded"}
        or result.get("tool_call_id") != effect["tool_call_id"]
        or result.get("action_name") != effect["action_name"]
        or datetime.fromisoformat(str(effect["expires_at"]).replace("Z", "+00:00"))
        > event.created_at
    ):
        raise AgUiProjectionError("expiry continuation lacks its exact native deadline")
    state.pending_effects.pop(str(effect_id))
    return {
        "effect_id": str(effect_id),
        "tool_call_id": str(effect["tool_call_id"]),
        "action_name": str(effect["action_name"]),
        "status": "expired",
    }
