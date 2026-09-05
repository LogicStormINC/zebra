"""Canonical cancellation mutation shared by authorized direct and command wrappers."""

from datetime import UTC, datetime
from typing import Any
from uuid import NAMESPACE_URL, UUID, uuid5

from agent_core.application import current_turn
from agent_core.application.session_projection import rebuild_session
from agent_core.application.workspace_projection import rebuild_workspace
from agent_core.domain.events import EventActor, EventType, SessionEvent
from agent_core.domain.identifiers import EventId, SessionId

from agent_storage.postgres.events import append_event_in_transaction
from agent_storage.postgres.leases import (
    _lock_epoch,
    _lock_lease_and_clock,
    lock_session_lease_boundary,
)
from agent_storage.postgres.projections import save_session_in_transaction
from agent_storage.postgres.workspaces import save_workspace_in_transaction


def lock_cancellation_context(
    connection: Any, namespace: str, session_id: SessionId
) -> tuple[list[SessionEvent], Any, datetime]:
    lock_session_lease_boundary(connection, namespace, session_id)
    _lock_epoch(connection, namespace)
    lease, _ = _lock_lease_and_clock(connection, namespace, session_id, update=True)
    stream = connection.execute(
        """SELECT current_version FROM session_streams WHERE deployment_namespace=%s
           AND session_id=%s FOR UPDATE""",
        (namespace, session_id),
    ).fetchone()
    if stream is None:
        raise ValueError("session was not found")
    now = connection.execute("SELECT clock_timestamp() AS now").fetchone()["now"].astimezone(UTC)
    # ponytail: cancellation replays the full Session, matching the existing control
    # projection contract. A proven snapshot boundary can replace this O(history) read.
    rows = connection.execute(
        """SELECT * FROM session_events WHERE deployment_namespace=%s AND session_id=%s
           ORDER BY sequence""",
        (namespace, session_id),
    ).fetchall()
    events = [SessionEvent.model_validate(row) for row in rows]
    if not events or events[-1].sequence != stream["current_version"]:
        raise ValueError("canonical Session stream is inconsistent")
    return events, lease, now


def cancel_in_transaction(
    connection: Any,
    namespace: str,
    events: list[SessionEvent],
    lease: Any,
    now: datetime,
    *,
    operation_id: UUID,
    command: bool,
) -> tuple[SessionEvent, Any]:
    """Caller holds Session→epoch/lease→stream and already checked caller authority."""
    session_id = events[0].session_id
    turn = current_turn(events)
    types = (
        []
        if turn is None
        else [
            (
                EventType.TURN_CANCELLED,
                {
                    "turn_id": turn.turn_id,
                    "turn_index": turn.turn_index,
                    "reason": "session_cancelled",
                },
            )
        ]
    )
    types.append((EventType.SESSION_CANCELLED, {}))
    prefix = "command-control" if command else "direct-control"
    identity = "zebra-control" if command else "zebra-direct-control"
    for event_type, payload in types:
        event = SessionEvent.create(
            session_id=session_id,
            sequence=events[-1].sequence + 1,
            event_type=event_type,
            actor=EventActor.SYSTEM,
            payload=payload,
            idempotency_key=f"{prefix}:{operation_id}:{event_type.value}",
            causation_id=EventId(operation_id) if command else None,
            created_at=now,
        ).model_copy(
            update={
                "event_id": uuid5(
                    NAMESPACE_URL, f"{identity}:{namespace}:{operation_id}:{event_type.value}"
                )
            }
        )
        events.append(append_event_in_transaction(connection, namespace, event))
    save_session_in_transaction(connection, namespace, rebuild_session(events))
    save_workspace_in_transaction(connection, namespace, rebuild_workspace(events))
    revoked = None
    if lease is not None and lease["released_at"] is None:
        connection.execute(
            """UPDATE worker_leases SET released_at=%s
               WHERE deployment_namespace=%s AND session_id=%s""",
            (now, namespace, session_id),
        )
        revoked = lease
    return events[-1], revoked
