"""Indexed Session pages and atomically fenced primary/index recovery slices."""

import json
from typing import Any

from agent_core.application.session_projection import apply_event as apply_session
from agent_core.application.workspace_projection import apply_event as apply_workspace
from agent_core.domain.events import EventType, SessionEvent
from agent_core.domain.identifiers import SessionId
from agent_core.domain.leases import LeaseLostError
from agent_core.domain.sessions import Session
from agent_core.domain.workspaces import WorkspaceProjection
from agent_core.ports.aggregate_mutation import WorkerMutationAuthority
from agent_core.ports.session_recovery import (
    SessionEventPage,
    SessionRecoveryCommit,
    SessionRecoveryConflict,
    SessionRecoveryHead,
)
from agent_core.ports.task_projection_checkpoints import CheckpointNotReady

from agent_storage.postgres.command_read_state import advance_command_read_page
from agent_storage.postgres.database import PostgresDatabase
from agent_storage.postgres.leases import assert_current_lease_fence, lock_session_lease_boundary
from agent_storage.postgres.model_tool_projections import index_event_in_transaction
from agent_storage.postgres.projections import (
    get_session_in_transaction,
    save_session_in_transaction,
)
from agent_storage.postgres.task_io import TaskIoConnections
from agent_storage.postgres.task_lineage import EVENT_COLUMNS
from agent_storage.postgres.workspaces import (
    get_workspace_in_transaction,
    save_workspace_in_transaction,
)
from agent_storage.task_event_page_limits import admitted_page_positions, validate_page_request

# Fixed point probes also keep small-table plans indexed: an ordinary range may
# legitimately choose a whole heap scan even though it returns only 256 rows.
SESSION_PAGE_METADATA_SQL = (
    "SELECT sequence,event_bytes_bound FROM generate_series(%s::bigint,%s::bigint) "
    "requested(position) CROSS JOIN LATERAL (SELECT sequence,event_bytes_bound "
    "FROM session_events WHERE deployment_namespace=%s AND session_id=%s "
    "AND sequence=requested.position LIMIT 1) canonical ORDER BY sequence LIMIT %s"
)


def lock_session_recovery_source(
    connection: Any,
    namespace: str,
    session_id: SessionId,
    authority: WorkerMutationAuthority,
) -> int:
    if authority.deployment_namespace != namespace or authority.session_id != session_id:
        raise LeaseLostError("Session recovery authority belongs to another namespace or Session")
    lock_session_lease_boundary(connection, namespace, session_id)
    assert_current_lease_fence(connection, namespace, session_id, authority.lease_fence)
    row = connection.execute(
        "SELECT current_version FROM session_streams "
        "WHERE deployment_namespace=%s AND session_id=%s FOR UPDATE",
        (namespace, session_id),
    ).fetchone()
    if row is None:
        raise SessionRecoveryConflict("cannot recover missing Session")
    return int(row["current_version"])


def read_session_page(
    connection: Any,
    namespace: str,
    session_id: SessionId,
    after: int,
    *,
    through: int,
    limit: int = 256,
    max_bytes: int = 1_048_576,
) -> SessionEventPage:
    validate_page_request(after, limit, max_bytes, through)
    source = connection.execute(
        "SELECT current_version FROM session_streams "
        "WHERE deployment_namespace=%s AND session_id=%s",
        (namespace, session_id),
    ).fetchone()
    if source is None or through > source["current_version"]:
        raise SessionRecoveryConflict("Session page highwater exceeds canonical source")
    metadata = connection.execute(
        SESSION_PAGE_METADATA_SQL,
        (after + 1, min(through, after + limit), namespace, session_id, limit),
    ).fetchall()
    if any(row["event_bytes_bound"] is None for row in metadata):
        raise CheckpointNotReady("Session Event byte bounds require explicit preparation")
    positions = admitted_page_positions(
        [(row["sequence"], row["event_bytes_bound"]) for row in metadata],
        after=after,
        highwater=through,
        max_bytes=max_bytes,
    )
    rows = (
        []
        if not positions
        else connection.execute(
            f"SELECT {EVENT_COLUMNS} FROM unnest(%s::bigint[]) requested(position) "
            f"CROSS JOIN LATERAL (SELECT {EVENT_COLUMNS} FROM session_events event "
            "WHERE deployment_namespace=%s AND session_id=%s "
            "AND sequence=requested.position LIMIT 1) event ORDER BY event.sequence LIMIT %s",
            (list(positions), namespace, session_id, len(positions)),
        ).fetchall()
    )
    if len(rows) != len(positions):
        raise SessionRecoveryConflict("Session page changed during canonical read")
    events = tuple(SessionEvent.model_validate(row) for row in rows)
    size = sum(
        len(
            json.dumps(
                event.model_dump(mode="json"), ensure_ascii=False, separators=(",", ":")
            ).encode()
        )
        for event in events
    )
    if size > max_bytes:
        raise SessionRecoveryConflict("Session page exceeds admitted byte budget")
    return SessionEventPage(session_id, events, after, through, size)


class PostgresSessionRecoveryStore:
    """Standalone cloud composition; primary adapters do not import recovery."""

    def __init__(
        self,
        dsn: str,
        *,
        deployment_namespace: str,
        task_io_connections: TaskIoConnections | None = None,
    ) -> None:
        self._database = PostgresDatabase(
            dsn, deployment_namespace=deployment_namespace, task_io_connections=task_io_connections
        )

    def read_session_recovery_head(
        self,
        session_id: SessionId,
        *,
        authority: WorkerMutationAuthority,
    ) -> SessionRecoveryHead:
        namespace = self._database.deployment_namespace
        with self._database.connect_task_io() as connection:
            highwater = lock_session_recovery_source(connection, namespace, session_id, authority)
            # Primary rows participate in the source-lock domain for this transaction.
            session, workspace = _primary(connection, namespace, session_id)
            if max(session.current_sequence, workspace.current_sequence) > highwater:
                raise SessionRecoveryConflict("primary projection exceeds canonical source")
            row = connection.execute(
                "INSERT INTO session_recovery_frontiers VALUES (%s,%s,-1,%s) "
                "ON CONFLICT (deployment_namespace,session_id) DO UPDATE SET highwater="
                "CASE WHEN session_recovery_frontiers.highwater<GREATEST(%s,%s) "
                "OR session_recovery_frontiers.highwater<=LEAST("
                "session_recovery_frontiers.index_sequence,%s,%s) THEN EXCLUDED.highwater "
                "ELSE session_recovery_frontiers.highwater END RETURNING highwater,index_sequence",
                (
                    namespace,
                    session_id,
                    highwater,
                    session.current_sequence,
                    workspace.current_sequence,
                    session.current_sequence,
                    workspace.current_sequence,
                ),
            ).fetchone()
            assert row is not None
            if row["highwater"] > highwater:
                raise SessionRecoveryConflict("recovery frontier exceeds canonical source")
            assert_current_lease_fence(connection, namespace, session_id, authority.lease_fence)
            return SessionRecoveryHead(row["highwater"], row["index_sequence"])

    def read_session_event_page(
        self,
        session_id: SessionId,
        after_sequence: int,
        *,
        through_sequence: int,
        limit: int = 256,
        max_bytes: int = 1_048_576,
    ) -> SessionEventPage:
        with self._database.connect_task_io() as connection:
            connection.execute("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY")
            return read_session_page(
                connection,
                self._database.deployment_namespace,
                session_id,
                after_sequence,
                through=through_sequence,
                limit=limit,
                max_bytes=max_bytes,
            )

    def commit_session_recovery_page(
        self,
        page: SessionEventPage,
        *,
        expected_index_sequence: int,
        authority: WorkerMutationAuthority,
    ) -> SessionRecoveryCommit:
        namespace, session_id = self._database.deployment_namespace, page.session_id
        with self._database.connect_task_io() as connection:
            highwater = lock_session_recovery_source(connection, namespace, session_id, authority)
            head = connection.execute(
                "SELECT highwater,index_sequence FROM session_recovery_frontiers "
                "WHERE deployment_namespace=%s AND session_id=%s FOR UPDATE",
                (namespace, session_id),
            ).fetchone()
            if (
                type(expected_index_sequence) is not int
                or (authority.expected_stream_revision != page.after_sequence)
                or head is None
                or head["index_sequence"] != expected_index_sequence
                or (head["highwater"] != page.highwater or page.highwater > highwater)
            ):
                raise SessionRecoveryConflict("Session recovery frontier CAS failed")
            session, workspace = _primary(connection, namespace, session_id)
            if page.after_sequence > min(
                session.current_sequence, workspace.current_sequence, expected_index_sequence
            ):
                raise SessionRecoveryConflict("Session recovery page skips durable coverage")
            if max(session.current_sequence, workspace.current_sequence) > highwater:
                raise SessionRecoveryConflict("primary projection exceeds canonical source")
            canonical = read_session_page(
                connection,
                namespace,
                session_id,
                page.after_sequence,
                through=page.highwater,
                limit=max(1, len(page.events)),
            )
            if canonical != page:
                raise SessionRecoveryConflict(
                    "Session recovery page conflicts with canonical source"
                )
            advance_command_read_page(connection, namespace, page)
            for event in page.events:
                if event.sequence > session.current_sequence:
                    session = apply_session(session, event)
                if event.sequence > workspace.current_sequence:
                    workspace = apply_workspace(workspace, event)
                if event.sequence > expected_index_sequence and event.event_type in {
                    EventType.MODEL_RESPONSE_RECEIVED,
                    EventType.TOOL_EXECUTION_COMPLETED,
                    EventType.TOOL_EXECUTION_FAILED,
                }:
                    index_event_in_transaction(connection, namespace, event)
            save_session_in_transaction(connection, namespace, session)
            save_workspace_in_transaction(connection, namespace, workspace)
            frontier = max(expected_index_sequence, page.next_sequence)
            connection.execute(
                "UPDATE session_recovery_frontiers SET index_sequence=%s "
                "WHERE deployment_namespace=%s AND session_id=%s",
                (frontier, namespace, session_id),
            )
            # Check again after projection/index row waits: expiration rolls back the whole Page.
            assert_current_lease_fence(connection, namespace, session_id, authority.lease_fence)
            return SessionRecoveryCommit(session, workspace, frontier)


def _primary(
    connection: Any, namespace: str, session_id: SessionId
) -> tuple[Session, WorkspaceProjection]:
    for table in ("session_projections", "workspace_projections"):
        connection.execute(
            f"SELECT current_sequence FROM {table} "
            "WHERE deployment_namespace=%s AND session_id=%s FOR UPDATE",
            (namespace, session_id),
        ).fetchone()
    session = get_session_in_transaction(connection, namespace, session_id)
    workspace = get_workspace_in_transaction(connection, namespace, session_id)
    if session is None or workspace is None:
        raise SessionRecoveryConflict("cloud recovery requires primary projections")
    return session, workspace
