"""Native bounded exact prefix preparation and command/control snapshot consumption.

Shared contract: callers hold Session -> epoch/lease -> stream for load/store.
Derived preparation acquires that same boundary, but never acquires/replaces a
worker lease: trusted control remains available after execution grant/lease expiry.
"""

import math
from time import monotonic
from typing import Any
from uuid import UUID

import psycopg
from agent_core.application.session_command_read_state import SessionCommandReadState
from agent_core.domain.events import EventType, SessionEvent
from agent_core.domain.identifiers import EventId, SessionId
from agent_core.ports.session_recovery import SessionEventPage
from agent_core.ports.task_projection_checkpoints import CheckpointConflict, CheckpointNotReady
from agent_core.ports.worker_preparation import PreparationAdvanced

from agent_storage.postgres.database import PostgresDatabase
from agent_storage.postgres.events import read_event_in_transaction
from agent_storage.postgres.leases import (
    _lock_epoch,
    _lock_lease_and_clock,
    lock_session_lease_boundary,
)
from agent_storage.postgres.task_io import task_io_deadline
from agent_storage.task_read_summary_rows import encoded


def lock_command_source(connection: Any, namespace: str, session_id: SessionId) -> int:
    lock_session_lease_boundary(connection, namespace, session_id)
    _lock_epoch(connection, namespace)
    _lock_lease_and_clock(connection, namespace, session_id, update=True)
    row = connection.execute(
        "SELECT current_version FROM session_streams WHERE deployment_namespace=%s "
        "AND session_id=%s FOR UPDATE",
        (namespace, session_id),
    ).fetchone()
    if row is None:
        raise ValueError("session was not found")
    return int(row["current_version"])


def _head(connection: Any, namespace: str, session_id: SessionId) -> Any:
    return connection.execute(
        "SELECT through_sequence,highwater,snapshot_json FROM session_command_read_heads "
        "WHERE deployment_namespace=%s AND session_id=%s FOR UPDATE",
        (namespace, session_id),
    ).fetchone()


def _state(
    connection: Any, namespace: str, session_id: SessionId, row: Any
) -> SessionCommandReadState:
    if row is None:
        return SessionCommandReadState()
    if len(row["snapshot_json"].encode()) > 1_048_576:
        raise CheckpointConflict("command snapshot exceeds byte budget")
    state = SessionCommandReadState.model_validate_json(row["snapshot_json"])
    if (
        state.through_sequence != row["through_sequence"]
        or (
            state.session is not None
            and (
                state.session.session_id != session_id
                or state.session.current_sequence != state.through_sequence
            )
        )
        or (
            state.workspace is not None
            and state.workspace.current_sequence != state.through_sequence
        )
    ):
        raise CheckpointConflict("command snapshot conflicts with its persisted prefix")
    if state.through_sequence >= 0:
        canonical = connection.execute(
            "SELECT event_id FROM session_events WHERE deployment_namespace=%s "
            "AND session_id=%s AND sequence=%s",
            (namespace, session_id, state.through_sequence),
        ).fetchone()
        if canonical is None or canonical["event_id"] != state.last_event_id:
            raise CheckpointConflict("command checkpoint frontier conflicts with canonical source")
    return state


def store_command_read_state(
    connection: Any,
    namespace: str,
    session_id: SessionId,
    state: SessionCommandReadState,
    *,
    expected: int,
    highwater: int,
) -> None:
    text = encoded(state.model_dump(mode="json"), 1_048_576)
    if expected == -1:
        connection.execute(
            "INSERT INTO session_command_read_heads VALUES (%s,%s,-1,%s,%s) ON CONFLICT DO NOTHING",
            (namespace, session_id, highwater, SessionCommandReadState().model_dump_json()),
        )
    changed = connection.execute(
        "UPDATE session_command_read_heads SET through_sequence=%s,highwater=%s,snapshot_json=%s "
        "WHERE deployment_namespace=%s AND session_id=%s AND through_sequence=%s",
        (state.through_sequence, highwater, text, namespace, session_id, expected),
    )
    if changed.rowcount != 1:
        raise CheckpointConflict("command checkpoint expected frontier changed")


def advance_command_read_page(connection: Any, namespace: str, page: SessionEventPage) -> None:
    """Called inside the existing fenced Session recovery commit, never writes Events."""
    row = _head(connection, namespace, page.session_id)
    state = _state(connection, namespace, page.session_id, row)
    if state.through_sequence < page.after_sequence:
        # Existing index coverage can precede v77; independent bounded preparation
        # replays the missing exact prefix instead of inferring it from projections.
        return
    if state.through_sequence >= page.next_sequence:
        return
    expected = state.through_sequence
    for event in page.events:
        if event.sequence > expected:
            state = state.advance(event)
            _archive_cancel_workspace(connection, namespace, state, event)
    store_command_read_state(
        connection,
        namespace,
        page.session_id,
        state,
        expected=expected,
        highwater=max(page.highwater, row["highwater"] if row else -1),
    )


def _archive_cancel_workspace(
    connection: Any,
    namespace: str,
    state: SessionCommandReadState,
    event: SessionEvent,
) -> None:
    if event.event_type is EventType.SESSION_CANCELLED and state.workspace is not None:
        connection.execute(
            "UPDATE direct_control_operations SET workspace_snapshot_json=%s "
            "WHERE deployment_namespace=%s AND terminal_event_id=%s "
            "AND workspace_snapshot_json IS NULL",
            (
                encoded(state.workspace.model_dump(mode="json"), 1_048_576),
                namespace,
                event.event_id,
            ),
        )


def load_command_read_state(
    connection: Any,
    namespace: str,
    session_id: SessionId,
    highwater: int,
) -> SessionCommandReadState:
    """Exact hot-path state: one checkpoint and at most one bounded canonical page."""
    from agent_storage.postgres.session_recovery import read_session_page

    row = _head(connection, namespace, session_id)
    state = _state(connection, namespace, session_id, row)
    if state.through_sequence > highwater:
        raise CheckpointConflict("command checkpoint exceeds canonical head")
    if highwater - state.through_sequence > 256:
        raise CheckpointNotReady("command read state requires bounded prefix preparation")
    page = read_session_page(
        connection, namespace, session_id, state.through_sequence, through=highwater
    )
    if page.next_sequence != highwater:
        raise CheckpointNotReady("command canonical tail requires further byte-bounded preparation")
    expected = state.through_sequence
    for event in page.events:
        state = state.advance(event)
        _archive_cancel_workspace(connection, namespace, state, event)
    if page.events:
        store_command_read_state(
            connection, namespace, session_id, state, expected=expected, highwater=highwater
        )
    if state.session is None or state.workspace is None:
        raise CheckpointNotReady("command snapshot lacks canonical Session/Workspace bootstrap")
    return state


def command_event_at(
    connection: Any,
    namespace: str,
    session_id: SessionId,
    event_id: UUID,
) -> SessionEvent | None:
    metadata = connection.execute(
        "SELECT event_bytes_bound FROM session_events WHERE deployment_namespace=%s "
        "AND session_id=%s AND event_id=%s",
        (namespace, session_id, event_id),
    ).fetchone()
    if metadata is None:
        return None
    bound = metadata["event_bytes_bound"]
    if type(bound) is not int or not 0 < bound <= 1_048_576:
        raise CheckpointNotReady("command canonical point evidence exceeds admission")
    return read_event_in_transaction(connection, namespace, EventId(event_id))


def prepare_command_read_state(
    dsn: str,
    *,
    deployment_namespace: str,
    session_id: SessionId,
) -> None:
    """One cumulative 2s slice; already committed Pages survive interruption."""
    from agent_storage.postgres.session_recovery import read_session_page

    database = PostgresDatabase(dsn, deployment_namespace=deployment_namespace)
    start: int | None = None
    through = -1
    highwater = -1
    deadline = monotonic() + 2
    try:
        with task_io_deadline(deadline):
            while True:
                with database.connect_task_io() as connection:
                    source = lock_command_source(connection, deployment_namespace, session_id)
                    row = _head(connection, deployment_namespace, session_id)
                    state = _state(connection, deployment_namespace, session_id, row)
                    if start is None:
                        start = state.through_sequence
                    highwater = (
                        row["highwater"]
                        if row and row["highwater"] > state.through_sequence
                        else source
                    )
                    if highwater > source:
                        raise CheckpointConflict("command captured head exceeds source")
                    page = read_session_page(
                        connection,
                        deployment_namespace,
                        session_id,
                        state.through_sequence,
                        through=highwater,
                    )
                    expected = state.through_sequence
                    for event in page.events:
                        state = state.advance(event)
                        _archive_cancel_workspace(connection, deployment_namespace, state, event)
                    store_command_read_state(
                        connection,
                        deployment_namespace,
                        session_id,
                        state,
                        expected=expected,
                        highwater=highwater,
                    )
                through = state.through_sequence
                if through == source:
                    return
                if monotonic() >= deadline - 0.05:
                    raise PreparationAdvanced(str(session_id), through, highwater)
    except (TimeoutError, psycopg.errors.QueryCanceled) as exc:
        if start is not None and through > start:
            raise PreparationAdvanced(str(session_id), through, highwater) from exc
        raise CheckpointNotReady("command preparation exceeded native storage deadline") from exc


def finish_command_read_state(
    dsn: str,
    *,
    deployment_namespace: str,
    session_id: SessionId,
    caller_budget_seconds: float = 2,
) -> None:
    """Bounded admission; PreparationAdvanced is durable continuation, not rejection.

    The caller must retry the same candidate/generation (without a lease) or
    prepare in the background. Never loop for hours in a control request.
    """
    if type(caller_budget_seconds) not in (int, float) or (
        not math.isfinite(caller_budget_seconds) or not 0 < caller_budget_seconds <= 2
    ):
        raise ValueError("command preparation caller budget must be in (0,2]")
    with task_io_deadline(monotonic() + caller_budget_seconds):
        prepare_command_read_state(
            dsn, deployment_namespace=deployment_namespace, session_id=session_id
        )


class CommandReadPreparing(RuntimeError):
    """Direct-control caller should retry preparation, not classify invalid authority."""
