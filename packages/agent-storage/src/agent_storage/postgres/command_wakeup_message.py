"""Canonical MESSAGE input uses Core validation inside the existing lease transaction."""

from datetime import UTC
from typing import Any
from uuid import NAMESPACE_URL, UUID, uuid5

from agent_core.application import (
    SessionMessageAppendCommand,
    SessionMessageAppendService,
    current_turn,
    project_turns,
)
from agent_core.application.session_projection import rebuild_session
from agent_core.application.workspace_projection import rebuild_workspace
from agent_core.domain.events import EventActor, EventType, SessionEvent
from agent_core.domain.identifiers import EventId

from agent_storage.postgres.events import append_event_in_transaction
from agent_storage.postgres.projections import save_session_in_transaction
from agent_storage.postgres.workspaces import save_workspace_in_transaction


class MessageInputRejected(ValueError):
    """Roll back tentative lease/input, then durably require reconciliation."""


def append_command_message(
    connection: Any,
    namespace: str,
    accepted: SessionEvent,
    *,
    input_event_id: UUID | None,
) -> SessionEvent:
    """Caller holds lease UPDATE then stream UPDATE until receipt/Inbox commit."""
    payload = accepted.payload.get("payload")
    if not isinstance(payload, dict):
        raise MessageInputRejected("invalid canonical message input")
    content = payload.get("content")
    clarification_id = payload.get("clarification_id")
    if (
        not isinstance(content, str)
        or not content.strip()
        or (clarification_id is not None and not isinstance(clarification_id, str))
    ):
        raise MessageInputRejected("invalid canonical message input")
    event_id = EventId(uuid5(NAMESPACE_URL, f"zebra-command-input:{namespace}:{accepted.event_id}"))
    key = f"command-input:{accepted.event_id}"
    # ponytail: replay is O(session history), matching Core Turn projection's
    # current API. A future indexed Turn projection can replace it; never truncate
    # history and thereby mistake an existing open Turn for an absent one.
    rows = connection.execute(
        """SELECT event_id, session_id, sequence, event_type, payload, actor, created_at,
                  causation_id, correlation_id, idempotency_key, policy_version, model_profile
           FROM session_events WHERE deployment_namespace = %s AND session_id = %s
           ORDER BY sequence""",
        (namespace, accepted.session_id),
    ).fetchall()
    events = [SessionEvent.model_validate(row) for row in rows]
    if input_event_id is not None:
        existing = next((event for event in events if event.event_id == input_event_id), None)
        expected_type = (
            EventType.USER_MESSAGE_RECEIVED
            if clarification_id is None
            else EventType.CLARIFICATION_RESPONDED
        )
        if (
            existing is None
            or input_event_id != event_id
            or existing.event_type is not expected_type
            or existing.actor is not EventActor.USER
            or existing.causation_id != accepted.event_id
            or existing.idempotency_key != key
            or existing.sequence <= accepted.sequence
            or existing.payload.get("content") != content.strip()
            or existing.payload.get("clarification_id") != clarification_id
        ):
            raise MessageInputRejected("canonical command input association mismatch")
        return existing
    if any(event.event_id == event_id for event in events):
        raise MessageInputRejected("canonical command input lacks its receipt association")
    now = connection.execute("SELECT clock_timestamp() AS now").fetchone()["now"].astimezone(UTC)
    try:
        event = SessionMessageAppendService().build_event(
            session=rebuild_session(events),
            next_sequence=events[-1].sequence + 1,
            command=SessionMessageAppendCommand(
                content=content,
                clarification_id=clarification_id,
                appended_at=now,
                prior_human_turns=len(project_turns(events)),
                open_turn_exists=current_turn(events) is not None,
            ),
        )
    except ValueError:
        raise MessageInputRejected("canonical message requires reconciliation") from None
    event = event.model_copy(
        update={
            "event_id": event_id,
            "idempotency_key": key,
            "causation_id": accepted.event_id,
            "correlation_id": accepted.correlation_id or accepted.event_id,
        }
    )
    canonical = append_event_in_transaction(connection, namespace, event)
    events.append(canonical)
    save_session_in_transaction(connection, namespace, rebuild_session(events))
    save_workspace_in_transaction(connection, namespace, rebuild_workspace(events))
    return canonical
