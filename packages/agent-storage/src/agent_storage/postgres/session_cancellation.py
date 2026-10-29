"""Canonical cancellation mutation shared by authorized direct and command wrappers."""

from datetime import UTC, datetime
from typing import Any
from uuid import NAMESPACE_URL, UUID, uuid5

from agent_core.application.session_command_read_state import SessionCommandReadState
from agent_core.domain.client_preparation import ClientPreparationContext
from agent_core.domain.events import EventActor, EventType, SessionEvent
from agent_core.domain.identifiers import EventId, SessionId

from agent_storage.postgres.command_read_state import (
    load_command_read_state,
    store_command_read_state,
)
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
) -> tuple[SessionCommandReadState, Any, datetime]:
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
    state = load_command_read_state(connection, namespace, session_id, stream["current_version"])
    return state, lease, now


def cancel_in_transaction(
    connection: Any,
    namespace: str,
    state: SessionCommandReadState,
    lease: Any,
    now: datetime,
    *,
    operation_id: UUID,
    command: bool,
    preparation: ClientPreparationContext | None = None,
) -> tuple[SessionEvent, Any]:
    """Caller holds Session→epoch/lease→stream and already checked caller authority."""
    assert state.session is not None and state.workspace is not None
    session_id = state.session.session_id
    expected = state.through_sequence
    turn = state.turns.current_turn()
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
    types.append(
        (
            EventType.SESSION_CANCELLED,
            {}
            if preparation is None
            else {
                "input": preparation.input,
                "client_preparation": preparation.model_dump(mode="json", exclude={"input"}),
            },
        )
    )
    prefix = "command-control" if command else "direct-control"
    identity = "zebra-control" if command else "zebra-direct-control"
    for event_type, payload in types:
        event = SessionEvent.create(
            session_id=session_id,
            sequence=state.through_sequence + 1,
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
        terminal = append_event_in_transaction(connection, namespace, event)
        state = state.advance(terminal)
    assert state.session is not None and state.workspace is not None
    save_session_in_transaction(connection, namespace, state.session)
    save_workspace_in_transaction(connection, namespace, state.workspace)
    store_command_read_state(
        connection,
        namespace,
        session_id,
        state,
        expected=expected,
        highwater=state.through_sequence,
    )
    revoked = None
    if lease is not None and lease["released_at"] is None:
        connection.execute(
            """UPDATE worker_leases SET released_at=%s
               WHERE deployment_namespace=%s AND session_id=%s""",
            (now, namespace, session_id),
        )
        revoked = lease
    return terminal, revoked
