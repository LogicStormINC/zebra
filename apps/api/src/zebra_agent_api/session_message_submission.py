"""Durable message-Event construction with ADR-026 Turn identity."""

from agent_core.application import (
    SessionMessageAppendCommand,
    SessionMessageAppendService,
    current_turn,
    project_turns,
)
from agent_core.domain.bundle_definition import BundleDefinitionSnapshot, parse_definition_snapshot
from agent_core.domain.events import EventType, SessionEvent
from agent_core.domain.runtime_bundle_types import ArtifactPin
from agent_core.domain.sessions import Session
from agent_core.ports import EventStorePort

from zebra_agent_api.responses import ApiResponse, conflict


def build_session_message_event(
    *,
    event_store: EventStorePort,
    session: Session,
    content: str,
    clarification_id: str | None,
    model_profile: str | None = None,
    reasoning_effort: str | None = None,
    selected_model_id: str | None = None,
) -> SessionEvent:
    """Build the next durable message Event with ADR-026 Turn identity."""

    events = event_store.list_for_session(session.session_id)
    selected_model_pin = None
    if clarification_id is None:
        prepared = next(
            (event for event in reversed(events) if event.event_type is EventType.TASK_PREPARED),
            None,
        )
        raw_snapshot = prepared.payload.get("definition_snapshot") if prepared is not None else None
        snapshot = parse_definition_snapshot(raw_snapshot) if raw_snapshot is not None else None
        if isinstance(snapshot, BundleDefinitionSnapshot):
            remembered = next(
                (
                    ArtifactPin.model_validate(raw).id
                    for event in reversed(events)
                    if event.event_type is EventType.USER_MESSAGE_RECEIVED
                    and (raw := event.payload.get("selected_model_pin")) is not None
                ),
                None,
            )
            assembly = snapshot.bound_version.runtime_assembly
            _, profile = assembly.resolve_session_model(
                requested_id=selected_model_id,
                remembered_id=remembered,
            )
            selected_model_pin = profile.pin
        elif selected_model_id is not None:
            raise ValueError("selected_model_requires_published_bundle")
    return SessionMessageAppendService().build_event(
        session=session,
        next_sequence=session.current_sequence + 1,
        command=SessionMessageAppendCommand(
            content=content,
            clarification_id=clarification_id,
            prior_human_turns=len(project_turns(events)),
            open_turn_exists=current_turn(events) is not None,
            model_profile=model_profile,
            reasoning_effort=reasoning_effort,
            selected_model_pin=selected_model_pin,
        ),
    )


def append_session_message_event(
    event_store: EventStorePort, event: SessionEvent
) -> SessionEvent | None:
    """Append a message event; None means a concurrent append won the race.

    Two concurrent appends can build the same next sequence: the loser
    reports a typed 409 sequence_conflict instead of a raw 500.
    """

    from agent_storage import (  # noqa: PLC0415
        SessionEventSequenceConflictError,
    )

    try:
        return event_store.append(event)
    except SessionEventSequenceConflictError:
        # Only a genuinely taken sequence maps to 409; event-id reuse and
        # idempotency-content conflicts fail closed with their own errors.
        return None


def message_sequence_conflict(session_id: str) -> ApiResponse:
    """Typed 409 for an append that lost the next-sequence race."""

    return conflict(
        session_id=session_id,
        status="sequence_conflict",
        reason="concurrent_append_won_the_sequence",
    )
