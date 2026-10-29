"""Separate answerable input, delivery completeness and operational pause facts."""

from ag_ui.core import (
    CustomEvent,
    Event,
    Interrupt,
    RunErrorEvent,
    RunFinishedCancelledOutcome,
    RunFinishedEvent,
    RunFinishedInterruptOutcome,
    StateDeltaEvent,
)
from agent_core.contracts.answer_events import DeliveryAssessmentPayload
from agent_core.domain.events import EventType, SessionEvent

from agent_integrations.ag_ui.contracts import AgUiRunIdentity
from agent_integrations.ag_ui.payload_validation import optional_payload_text
from agent_integrations.ag_ui.standard_state import (
    PUBLIC_PAUSE_DIAGNOSTICS,
    StandardProjectionState,
)
from agent_integrations.ag_ui.standard_usage import terminal_usage
from agent_integrations.coverage_public_events import coverage_projection_event


def execution_patch(
    state: StandardProjectionState, value: dict[str, object], timestamp: int
) -> StateDeltaEvent:
    state.public_execution = dict(value)
    # Root-level add preserves every other state branch; no full history replacement.
    return StateDeltaEvent.model_validate(
        {
            "timestamp": timestamp,
            "delta": [{"op": "add", "path": "/execution", "value": value}],
        }
    )


def input_or_pause(
    event: SessionEvent,
    identity: AgUiRunIdentity,
    state: StandardProjectionState,
) -> tuple[Event, ...]:
    kind, payload = event.event_type, event.payload
    timestamp = int(event.created_at.timestamp() * 1000)
    usage = terminal_usage(state)
    if kind in {EventType.APPROVAL_REQUESTED, EventType.CLARIFICATION_REQUESTED}:
        clarification = kind is EventType.CLARIFICATION_REQUESTED
        raw_id = optional_payload_text(
            payload, "clarification_id" if clarification else "tool_call_id"
        )
        interrupt = Interrupt(
            id=("clarification:" if clarification else "approval:")
            + (raw_id or str(event.event_id)),
            reason="clarification_required" if clarification else "approval_required",
            message=optional_payload_text(payload, "question" if clarification else "reason")
            or ("Clarification is required." if clarification else "Approval is required."),
            tool_call_id=None if clarification else raw_id,
            response_schema=payload.get("response_schema") if clarification else None,
        )
        state.open_interrupts[interrupt.id] = interrupt
        state.turn_finished = True
        return (
            execution_patch(
                state, {"status": "waiting_input", "openInterruptIds": [interrupt.id]}, timestamp
            ),
            RunFinishedEvent(
                timestamp=timestamp,
                thread_id=identity.thread_id,
                run_id=str(state.protocol_run_id),
                usage=usage,
                outcome=RunFinishedInterruptOutcome(interrupts=[interrupt]),
            ),
        )
    if kind in {EventType.HARNESS_ATTEMPT_STARTED, EventType.SESSION_RESUMED}:
        return (
            execution_patch(
                state,
                {
                    "status": "running"
                    if kind is EventType.HARNESS_ATTEMPT_STARTED
                    else "resuming",
                },
                timestamp,
            ),
        )
    if kind not in {
        EventType.SESSION_SUSPENDED,
        EventType.SESSION_HANDOFF_WORKSPACE_DRIFT_DETECTED,
    } or (kind is EventType.SESSION_SUSPENDED and payload.get("reason") == "waiting_children"):
        return ()
    reason = (
        "workspace_changed"
        if kind is EventType.SESSION_HANDOFF_WORKSPACE_DRIFT_DETECTED
        else payload.get("reason")
    )
    if reason in {"delivery_requirements_unmet", "verification_required"}:
        metadata = payload.get("metadata")
        raw = metadata.get("delivery_assessment") if isinstance(metadata, dict) else None
        assessment = DeliveryAssessmentPayload.model_validate(raw) if raw is not None else None
        state.turn_finished = True
        assessment_frames: tuple[Event, ...] = (
            (
                CustomEvent(
                    timestamp=timestamp,
                    name="zebra.delivery_assessment.v1",
                    value=assessment.model_dump(mode="json", exclude_none=True),
                ),
            )
            if assessment is not None
            else ()
        )
        return (
            *assessment_frames,
            execution_patch(
                state, {"status": "paused", "diagnostic": "delivery_incomplete"}, timestamp
            ),
            RunFinishedEvent(
                timestamp=timestamp,
                thread_id=identity.thread_id,
                run_id=str(state.protocol_run_id),
                usage=usage,
                outcome=RunFinishedCancelledOutcome(),
            ),
        )
    # Operational stops never fabricate human input; actual service faults are protocol errors.
    # A missing reason can be the user's snapshot pause; never expose paths/runtime.
    diagnostic = (
        reason
        if reason
        in {
            "model_call_budget_exhausted",
            "tool_call_budget_exhausted",
            "execution_storage_contention",
            "execution_storage_unavailable",
            "execution_authority_unavailable",
            "plugin_authority_unavailable",
            "workspace_changed",
        }
        else "execution_paused"
    )
    state.turn_finished = True
    return (
        execution_patch(state, {"status": "paused", "diagnostic": diagnostic}, timestamp),
        (
            RunErrorEvent(
                timestamp=timestamp,
                message="A required service or authority is unavailable; execution is paused.",
                code="zebra_execution_paused",
                usage=usage,
            )
            if diagnostic
            in {
                "execution_storage_contention",
                "execution_storage_unavailable",
                "execution_authority_unavailable",
                "plugin_authority_unavailable",
            }
            else RunFinishedEvent(
                timestamp=timestamp,
                thread_id=identity.thread_id,
                run_id=str(state.protocol_run_id),
                usage=usage,
                outcome=RunFinishedCancelledOutcome(),
            )
        ),
    )


def standard_public_event(event: SessionEvent, *, strict: bool) -> SessionEvent | None:
    """Run the shared privacy filter first; retain only typed lifecycle classification."""
    public = coverage_projection_event(event, strict=strict)
    if not strict:
        return public
    if event.event_type is EventType.SESSION_HANDOFF_WORKSPACE_DRIFT_DETECTED:
        return event.model_copy(update={"payload": {}})
    if event.event_type is EventType.SESSION_SUSPENDED:
        reason = event.payload.get("reason")
        allowed = PUBLIC_PAUSE_DIAGNOSTICS | {
            "waiting_children",
            "delivery_requirements_unmet",
            "verification_required",
        }
        safe = (
            reason if isinstance(reason, str) and reason in allowed else "coverage_execution_ended"
        )
        return event.model_copy(update={"payload": {"reason": safe}})
    return public
