"""No-dispatch settlement when an authoritative Effect payload cannot be read."""

from collections.abc import Callable
from contextlib import AbstractContextManager
from uuid import UUID

from agent_core.domain.effect_dispatch import EffectClaim, EffectDispatchStateError, EffectEvidence
from agent_core.domain.events import EventActor, EventType, SessionEvent
from agent_core.domain.identifiers import ToolCallId
from agent_core.domain.tools import ToolCall, ToolCallStatus
from agent_core.ports.effect_dispatch import EffectDispatchPort


def settle_unreadable_payload(
    claim: EffectClaim,
    error: BaseException,
    *,
    dispatch: EffectDispatchPort,
    ownership_check: Callable[[], None],
    mutation_guard: Callable[[], AbstractContextManager[object]],
    next_event: Callable[[EventType, EventActor, dict[str, object]], SessionEvent],
    accept_event: Callable[[SessionEvent], object],
) -> ToolCall | None:
    identity: ToolCall | None = None
    try:
        intent = dispatch.read_intent_event(claim.dispatch)
        attempt = intent.payload.get("attempt_number")
        call_id = intent.payload.get("tool_call_id")
        if (
            intent.event_id != claim.dispatch.intent_event_id
            or intent.session_id != claim.dispatch.execution_session_id
            or intent.event_type is not EventType.TOOL_EXECUTION_STARTED
            or intent.payload.get("tool_name") != claim.dispatch.identity.tool_name
            or type(attempt) is not int
            or attempt < 1
            or not isinstance(call_id, str)
        ):
            raise EffectDispatchStateError("Effect intent identity is invalid")
        # Identity-only observer adapter, never an executable recovered request.
        identity = ToolCall(
            tool_call_id=ToolCallId(UUID(call_id)),
            name=claim.dispatch.identity.tool_name,
            arguments={},
            created_at=intent.created_at,
        )
        with mutation_guard():
            ownership_check()
            terminal = next_event(
                EventType.TOOL_EXECUTION_FAILED,
                EventActor.HARNESS,
                {
                    "tool_call_id": call_id,
                    "tool_name": identity.name,
                    "attempt_number": attempt,
                    "status": ToolCallStatus.FAILED.value,
                    "output": "",
                    "metadata": {
                        "effect_status": "failed_no_effect",
                        "execution_state": "not_executed",
                    },
                },
            )
            persisted = dispatch.fail_no_effect(
                claim,
                evidence=EffectEvidence(reason_code="payload_not_admitted"),
                terminal_event=terminal,
            )
            accept_event(persisted)
    except BaseException as recovery_error:
        # Cleanup cannot replace the failure that already stops execution.
        error.add_note(f"Effect payload admission settlement failed: {recovery_error}")
    return identity
