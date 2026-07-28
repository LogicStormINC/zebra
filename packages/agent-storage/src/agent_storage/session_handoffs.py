from __future__ import annotations

import json
import sqlite3
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import UUID, uuid4

from agent_core.domain.events import EventType
from agent_core.domain.identifiers import HandoffId, SessionId, new_handoff_id, new_session_id
from agent_core.domain.leases import LeaseFence
from agent_core.domain.session_handoff import (
    HandoffOperationStatus,
    SessionHandoffEnvelope,
    SessionLineage,
    WorkspaceBindingRevision,
)
from agent_core.domain.sessions import SessionStatus
from agent_core.ports.handoff_dispatch_store import HandoffDispatch
from agent_core.ports.session_handoff import (
    HandoffOperation,
    HandoffSourceFacts,
    SessionHandoffCommitRequest,
    SessionHandoffCreateRequest,
    SessionHandoffPort,
    SessionHandoffResult,
)

from agent_storage.agent_tasks import TASK_SCHEMA, attach_handoff_segment_locked
from agent_storage.database import SQLiteDatabase
from agent_storage.leases import SQLiteLeaseStore
from agent_storage.projections import SQLiteProjectionStore
from agent_storage.session_handoff_events import build_handoff_events, insert_child_projections
from agent_storage.session_handoff_facts import read_source_facts
from agent_storage.session_handoff_rows import (
    INSERT_HANDOFF_OPERATION,
    SCHEMA,
    HandoffIdempotencyConflictError,
    HandoffStorageConflictError,
    insert_event,
    lineage_from_row,
    migrate_handoff_fence_columns,
    operation_from_row,
    operation_values,
    sha256_text,
)
from agent_storage.sqlite import SQLiteEventStore
from agent_storage.workspaces import SQLiteWorkspaceProjectionStore


class SQLiteSessionHandoffStore(SessionHandoffPort):
    def __init__(self, database_path: str | Path) -> None:
        self._database = SQLiteDatabase(database_path)
        SQLiteEventStore(database_path)
        SQLiteProjectionStore(database_path)
        SQLiteWorkspaceProjectionStore(database_path)
        SQLiteLeaseStore(database_path)
        self._initialize()

    def inspect_source_facts(self, session_id: SessionId, *, at: datetime) -> HandoffSourceFacts:
        with self._database.connect() as connection:
            return read_source_facts(connection, session_id, at=at)

    def reserve(
        self,
        request: SessionHandoffCreateRequest,
        *,
        request_hash: str,
        expected_source_stream_version: int,
        source_lease_fence: LeaseFence | None,
        authority_revision: str,
        workspace_revision: WorkspaceBindingRevision,
        task_profile_revision: str,
        effective_depth_limit: int,
    ) -> HandoffOperation:
        if not request.idempotency_key.strip() or not request_hash.strip():
            raise ValueError("handoff idempotency key and request hash must not be blank")
        now = datetime.now(UTC)
        operation = HandoffOperation(
            operation_id=str(uuid4()),
            status=HandoffOperationStatus.PREPARING,
            source_session_id=request.source_session_id,
            target_session_id=new_session_id(),
            handoff_id=new_handoff_id(),
            idempotency_key_hash=sha256_text(request.idempotency_key),
            request_hash=request_hash,
            expected_source_stream_version=expected_source_stream_version,
            source_lease_fence=source_lease_fence,
            authority_revision=authority_revision,
            workspace_revision=workspace_revision,
            task_profile_revision=task_profile_revision,
            effective_depth_limit=effective_depth_limit,
            artifact_id=None,
            created_at=now,
            updated_at=now,
        )
        with self._database.connect() as connection:
            existing = connection.execute(
                """
                SELECT * FROM handoff_operations
                WHERE source_session_id = ? AND idempotency_key_hash = ?
                """,
                (str(request.source_session_id), operation.idempotency_key_hash),
            ).fetchone()
            if existing is not None:
                stored = operation_from_row(existing)
                if stored.request_hash != request_hash:
                    raise HandoffIdempotencyConflictError(
                        "handoff idempotency key reused with different request"
                    )
                return stored
            connection.execute(INSERT_HANDOFF_OPERATION, operation_values(operation))
        return operation

    def commit(self, request: SessionHandoffCommitRequest) -> SessionHandoffResult:
        try:
            with self._database.connect() as connection:
                connection.execute("BEGIN IMMEDIATE")
                operation = self._locked_operation(connection, request.operation.operation_id)
                if operation.status is HandoffOperationStatus.COMMITTED:
                    return self._result_for_operation(connection, operation, replay=True)
                if operation.status is HandoffOperationStatus.ABORTED:
                    raise HandoffStorageConflictError("handoff operation is aborted")
                self._validate_commit(connection, operation, request)
                result = self._commit_locked(connection, operation, request)
                return result
        except sqlite3.IntegrityError as exc:
            self._abort_after_conflict(request.operation.operation_id, "handoff_successor_conflict")
            raise HandoffStorageConflictError("handoff successor or event conflict") from exc

    def abort(self, operation_id: str, *, code: str) -> HandoffOperation:
        if not code.strip():
            raise ValueError("handoff abort code must not be blank")
        with self._database.connect() as connection:
            operation = self._locked_operation(connection, operation_id)
            if operation.status is HandoffOperationStatus.COMMITTED:
                raise HandoffStorageConflictError("committed handoff cannot be aborted")
            connection.execute(
                """
                UPDATE handoff_operations
                SET status = ?, abort_code = ?, updated_at = ?
                WHERE operation_id = ?
                """,
                (
                    HandoffOperationStatus.ABORTED.value,
                    code,
                    datetime.now(UTC).isoformat(),
                    operation_id,
                ),
            )
            row = connection.execute(
                "SELECT * FROM handoff_operations WHERE operation_id = ?", (operation_id,)
            ).fetchone()
            assert row is not None
            return operation_from_row(row)

    def get_handoff(self, handoff_id: HandoffId) -> SessionHandoffResult | None:
        with self._database.connect() as connection:
            row = connection.execute(
                "SELECT * FROM handoff_operations WHERE handoff_id = ? AND status = ?",
                (str(handoff_id), HandoffOperationStatus.COMMITTED.value),
            ).fetchone()
            if row is None:
                return None
            return self._result_for_operation(connection, operation_from_row(row), replay=False)

    def get_envelope(self, handoff_id: HandoffId) -> SessionHandoffEnvelope | None:
        with self._database.connect() as connection:
            row = connection.execute(
                "SELECT envelope_json FROM session_handoff_envelopes WHERE handoff_id = ?",
                (str(handoff_id),),
            ).fetchone()
        return None if row is None else SessionHandoffEnvelope.model_validate_json(row[0])

    def get_lineage(self, session_id: SessionId) -> tuple[SessionLineage, ...]:
        with self._database.connect() as connection:
            row = connection.execute(
                "SELECT root_session_id FROM session_lineage WHERE session_id = ?",
                (str(session_id),),
            ).fetchone()
            if row is None:
                return ()
            rows = connection.execute(
                "SELECT * FROM session_lineage WHERE root_session_id = ? ORDER BY stage_index",
                (row[0],),
            ).fetchall()
        return tuple(lineage_from_row(item) for item in rows)

    def rebuild_lineage_index(self) -> int:
        with self._database.connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            rows = connection.execute(
                """
                SELECT session_id, payload FROM session_events
                WHERE event_type = ? ORDER BY created_at, session_id, sequence
                """,
                (EventType.SESSION_HANDOFF_RECEIVED.value,),
            ).fetchall()
            connection.execute("DELETE FROM session_lineage")
            for row in rows:
                payload = json.loads(row["payload"])
                connection.execute(
                    "INSERT OR IGNORE INTO session_lineage VALUES (?, ?, NULL, NULL, 0)",
                    (payload["root_session_id"], payload["root_session_id"]),
                )
                connection.execute(
                    "INSERT INTO session_lineage VALUES (?, ?, ?, ?, ?)",
                    (
                        row["session_id"],
                        payload["root_session_id"],
                        payload["parent_session_id"],
                        payload["handoff_id"],
                        payload["stage_index"],
                    ),
                )
            return len(rows)

    def abort_stale_preparing(self, *, before: datetime) -> int:
        if before.tzinfo is None:
            raise ValueError("stale handoff cutoff must be timezone-aware")
        with self._database.connect() as connection:
            cursor = connection.execute(
                """
                UPDATE handoff_operations
                SET status = 'aborted', abort_code = 'handoff_operation_stale', updated_at = ?
                WHERE status = 'preparing' AND updated_at < ?
                """,
                (datetime.now(UTC).isoformat(), before.isoformat()),
            )
            return cursor.rowcount

    def claim_dispatch(
        self,
        *,
        worker_id: str,
        claimed_at: datetime,
        lease_seconds: int = 60,
    ) -> HandoffDispatch | None:
        if not worker_id.strip() or lease_seconds <= 0 or claimed_at.tzinfo is None:
            raise ValueError("dispatch claim requires worker, positive lease and aware time")
        expires_at = claimed_at + timedelta(seconds=lease_seconds)
        with self._database.connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            row = connection.execute(
                """
                SELECT * FROM handoff_dispatch_outbox
                WHERE status = 'pending'
                   OR (status = 'claimed' AND claim_expires_at <= ?)
                ORDER BY created_at, delivery_id LIMIT 1
                """,
                (claimed_at.isoformat(),),
            ).fetchone()
            if row is None:
                return None
            connection.execute(
                """
                UPDATE handoff_dispatch_outbox
                SET status = 'claimed', claimed_by = ?, claim_expires_at = ?
                WHERE delivery_id = ?
                """,
                (worker_id, expires_at.isoformat(), row["delivery_id"]),
            )
            return HandoffDispatch(
                delivery_id=row["delivery_id"],
                child_session_id=SessionId(UUID(row["child_session_id"])),
                handoff_id=HandoffId(UUID(row["handoff_id"])),
                status="claimed",
                claimed_by=worker_id,
                claim_expires_at=expires_at,
            )

    def acknowledge_dispatch(self, delivery_id: str, *, worker_id: str) -> None:
        with self._database.connect() as connection:
            cursor = connection.execute(
                """
                UPDATE handoff_dispatch_outbox
                SET status = 'acked', claim_expires_at = NULL
                WHERE delivery_id = ? AND status = 'claimed' AND claimed_by = ?
                """,
                (delivery_id, worker_id),
            )
            if cursor.rowcount != 1:
                raise HandoffStorageConflictError("dispatch claim is not owned by worker")

    def _validate_commit(
        self,
        connection: sqlite3.Connection,
        operation: HandoffOperation,
        request: SessionHandoffCommitRequest,
    ) -> None:
        if operation != request.operation:
            raise HandoffStorageConflictError("handoff reservation facts changed")
        envelope = request.envelope
        if (
            envelope.handoff_id != operation.handoff_id
            or envelope.source_session_id != operation.source_session_id
            or envelope.target_session_id != operation.target_session_id
            or envelope.checksum != envelope.expected_checksum()
        ):
            raise HandoffStorageConflictError("handoff envelope does not match reservation")
        source = connection.execute(
            "SELECT status, current_sequence FROM session_projections WHERE session_id = ?",
            (str(operation.source_session_id),),
        ).fetchone()
        if source is None or source["status"] not in {
            SessionStatus.COMPLETED.value,
            SessionStatus.CANCELLED.value,
            SessionStatus.SUSPENDED.value,
            SessionStatus.FAILED.value,
        }:
            raise HandoffStorageConflictError("handoff source is not at a safe boundary")
        facts = read_source_facts(
            connection,
            operation.source_session_id,
            at=request.envelope.created_at,
        )
        if facts.has_active_lease:
            raise HandoffStorageConflictError("handoff source has an active lease")
        if (
            facts.stream_version != operation.expected_source_stream_version
            or source["current_sequence"] != facts.stream_version
            or facts.lease_fence != operation.source_lease_fence
            or facts.authority_revision != operation.authority_revision
            or facts.workspace_revision != operation.workspace_revision
            or facts.task_profile_revision != operation.task_profile_revision
            or facts.effective_depth_limit != operation.effective_depth_limit
        ):
            raise HandoffStorageConflictError("handoff source reservation facts changed")
        workspace = connection.execute(
            "SELECT * FROM workspace_projections WHERE session_id = ?",
            (str(operation.source_session_id),),
        ).fetchone()
        if workspace is None:
            raise HandoffStorageConflictError("handoff source workspace is missing")
        lineage = connection.execute(
            "SELECT * FROM session_lineage WHERE session_id = ?",
            (str(operation.source_session_id),),
        ).fetchone()
        source_stage = 0 if lineage is None else lineage["stage_index"]
        source_root = (
            operation.source_session_id if lineage is None else SessionId(UUID(lineage[1]))
        )
        if (
            envelope.source_stage_index != source_stage
            or envelope.root_session_id != source_root
            or envelope.target_stage_index > operation.effective_depth_limit
        ):
            raise HandoffStorageConflictError("handoff stage or depth changed")

    def _commit_locked(
        self,
        connection: sqlite3.Connection,
        operation: HandoffOperation,
        request: SessionHandoffCommitRequest,
    ) -> SessionHandoffResult:
        envelope = request.envelope
        workspace = connection.execute(
            "SELECT * FROM workspace_projections WHERE session_id = ?",
            (str(operation.source_session_id),),
        ).fetchone()
        assert workspace is not None
        source_lineage = connection.execute(
            "SELECT * FROM session_lineage WHERE session_id = ?",
            (str(operation.source_session_id),),
        ).fetchone()
        if source_lineage is None:
            connection.execute(
                "INSERT INTO session_lineage VALUES (?, ?, NULL, NULL, 0)",
                (str(operation.source_session_id), str(operation.source_session_id)),
            )
        connection.execute(
            "INSERT INTO session_handoff_envelopes VALUES (?, ?, ?, ?, ?, ?)",
            (
                str(operation.handoff_id),
                str(operation.source_session_id),
                str(operation.target_session_id),
                request.artifact_id,
                envelope.model_dump_json(),
                envelope.checksum,
            ),
        )
        events = build_handoff_events(operation, request, workspace)
        for event in events:
            insert_event(connection, event)
        parent_sequence = operation.expected_source_stream_version + 1
        connection.execute(
            """
            UPDATE session_projections
            SET current_sequence = ?, updated_at = ? WHERE session_id = ?
            """,
            (parent_sequence, envelope.created_at.isoformat(), str(operation.source_session_id)),
        )
        insert_child_projections(connection, operation, request, workspace)
        attached = attach_handoff_segment_locked(
            connection,
            root_session_id=envelope.root_session_id,
            segment_id=operation.target_session_id,
            predecessor_id=operation.source_session_id,
            handoff_reason=envelope.reason.value,
        )
        if not attached:
            raise HandoffStorageConflictError("handoff successor or active Segment conflict")
        connection.execute(
            "INSERT INTO session_lineage VALUES (?, ?, ?, ?, ?)",
            (
                str(operation.target_session_id),
                str(envelope.root_session_id),
                str(operation.source_session_id),
                str(operation.handoff_id),
                envelope.target_stage_index,
            ),
        )
        connection.execute(
            "INSERT INTO handoff_dispatch_outbox VALUES (?, ?, ?, 'pending', NULL, NULL, ?)",
            (
                str(operation.target_session_id),
                str(operation.target_session_id),
                str(operation.handoff_id),
                envelope.created_at.isoformat(),
            ),
        )
        connection.execute(
            """
            UPDATE handoff_operations
            SET status = ?, artifact_id = ?, updated_at = ? WHERE operation_id = ?
            """,
            (
                HandoffOperationStatus.COMMITTED.value,
                request.artifact_id,
                envelope.created_at.isoformat(),
                operation.operation_id,
            ),
        )
        committed = replace(
            operation,
            status=HandoffOperationStatus.COMMITTED,
            artifact_id=request.artifact_id,
            updated_at=envelope.created_at,
        )
        return self._result_for_operation(connection, committed, replay=False)

    def _result_for_operation(
        self,
        connection: sqlite3.Connection,
        operation: HandoffOperation,
        *,
        replay: bool,
    ) -> SessionHandoffResult:
        row = connection.execute(
            "SELECT * FROM session_lineage WHERE session_id = ?",
            (str(operation.target_session_id),),
        ).fetchone()
        status = connection.execute(
            "SELECT status FROM session_projections WHERE session_id = ?",
            (str(operation.target_session_id),),
        ).fetchone()
        if row is None or status is None or operation.artifact_id is None:
            raise HandoffStorageConflictError("committed handoff read model is incomplete")
        envelope = connection.execute(
            "SELECT checksum FROM session_handoff_envelopes WHERE handoff_id = ?",
            (str(operation.handoff_id),),
        ).fetchone()
        assert envelope is not None
        return SessionHandoffResult(
            handoff_id=operation.handoff_id,
            source_session_id=operation.source_session_id,
            child_session_id=operation.target_session_id,
            lineage=lineage_from_row(row),
            artifact_id=operation.artifact_id,
            checksum=envelope[0],
            child_status=status[0],
            idempotent_replay=replay,
        )

    def _locked_operation(
        self, connection: sqlite3.Connection, operation_id: str
    ) -> HandoffOperation:
        row = connection.execute(
            "SELECT * FROM handoff_operations WHERE operation_id = ?", (operation_id,)
        ).fetchone()
        if row is None:
            raise HandoffStorageConflictError("handoff operation not found")
        return operation_from_row(row)

    def _abort_after_conflict(self, operation_id: str, code: str) -> None:
        try:
            self.abort(operation_id, code=code)
        except HandoffStorageConflictError:
            pass

    def _initialize(self) -> None:
        with self._database.connect() as connection:
            connection.executescript(SCHEMA)
            connection.executescript(TASK_SCHEMA)
            migrate_handoff_fence_columns(connection, at=datetime.now(UTC))
