"""Atomic PostgreSQL Handoff operation, Event, projection and Task aggregate."""

from __future__ import annotations

from datetime import datetime
from uuid import UUID, uuid4

from agent_core.domain.identifiers import HandoffId, SessionId, TaskId
from agent_core.domain.leases import LeaseFence
from agent_core.domain.session_handoff import (
    HandoffOperationStatus,
    SessionHandoffEnvelope,
    SessionLineage,
    WorkspaceBindingRevision,
)
from agent_core.ports.aggregate_mutation import AdministrativeMutationCAS
from agent_core.ports.handoff_dispatch_store import HandoffDispatch
from agent_core.ports.session_handoff import (
    HandoffOperation,
    HandoffSourceFacts,
    SessionHandoffAbortPort,
    SessionHandoffAbortRequest,
    SessionHandoffCommitRequest,
    SessionHandoffCreateRequest,
    SessionHandoffPort,
    SessionHandoffResult,
)
from psycopg import errors
from psycopg.types.json import Jsonb

from agent_storage.postgres.database import PostgresDatabase
from agent_storage.postgres.leases import lock_session_lease_boundary
from agent_storage.postgres.session_handoff_authority import (
    abort_authorized_in_transaction,
    find_reservation,
    require_reservation_facts,
)
from agent_storage.postgres.session_handoff_facts import (
    operation_from_row,
    read_source_facts_in_transaction,
    sha256_text,
)
from agent_storage.postgres.session_handoff_transactions import (
    commit_handoff_in_transaction,
    lock_operation,
    result_for_operation,
)
from agent_storage.postgres.task_index_transactions import rebuild_task_in_transaction
from agent_storage.postgres.task_lineage import (
    PostgresAgentTaskConflictError,
    root_for_session,
)
from agent_storage.session_handoff_rows import (
    HandoffIdempotencyConflictError,
    HandoffStorageConflictError,
)


class PostgresSessionHandoffStore(SessionHandoffPort, SessionHandoffAbortPort):
    def __init__(self, dsn: str, *, deployment_namespace: str) -> None:
        self._database = PostgresDatabase(dsn, deployment_namespace=deployment_namespace)

    def inspect_source_facts(
        self,
        session_id: SessionId,
        *,
        at: datetime,
    ) -> HandoffSourceFacts:
        with self._database.connect() as connection:
            return read_source_facts_in_transaction(
                connection,
                self._database.deployment_namespace,
                session_id,
                at=at,
            )

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
        _require_sha256(request_hash, field_name="request_hash")
        if not request.idempotency_key.strip():
            raise ValueError("handoff idempotency key must not be blank")
        namespace = self._database.deployment_namespace
        idempotency_hash = sha256_text(request.idempotency_key)
        with self._database.connect() as connection:
            now_row = connection.execute(
                "SELECT transaction_timestamp() AS now"
            ).fetchone()
            assert now_row is not None
            now = now_row["now"]
            existing = find_reservation(
                connection,
                namespace,
                request.source_session_id,
                idempotency_hash,
            )
            if existing is not None:
                if existing["request_hash"] != request_hash:
                    raise HandoffIdempotencyConflictError(
                        "handoff idempotency key reused with different request"
                    )
                return operation_from_row(existing)
            lock_session_lease_boundary(
                connection,
                namespace,
                request.source_session_id,
            )
            existing = find_reservation(
                connection,
                namespace,
                request.source_session_id,
                idempotency_hash,
            )
            if existing is not None:
                if existing["request_hash"] != request_hash:
                    raise HandoffIdempotencyConflictError(
                        "handoff idempotency key reused with different request"
                    )
                return operation_from_row(existing)
            try:
                facts = read_source_facts_in_transaction(
                    connection,
                    namespace,
                    request.source_session_id,
                    at=now,
                    lock_workspace=True,
                    lock_stream=True,
                )
            except ValueError as error:
                raise HandoffStorageConflictError(
                    "handoff source authority facts are unavailable"
                ) from error
            require_reservation_facts(
                facts,
                expected_source_stream_version=expected_source_stream_version,
                source_lease_fence=source_lease_fence,
                authority_revision=authority_revision,
                workspace_revision=workspace_revision,
                task_profile_revision=task_profile_revision,
            )
            fence = source_lease_fence
            row = connection.execute(
                """
                INSERT INTO handoff_operations (
                    deployment_namespace, operation_id, status, source_session_id,
                    target_session_id, handoff_id, idempotency_key_hash, request_hash,
                    expected_source_stream_version, source_lease_epoch,
                    source_lease_fencing_token, source_lease_owner_instance_id,
                    authority_revision, workspace_revision, task_profile_revision,
                    effective_depth_limit, created_at, updated_at
                ) VALUES (
                    %s, %s, 'preparing', %s, %s, %s, %s, %s, %s,
                    %s, %s, %s, %s, %s, %s, %s, %s, %s
                )
                ON CONFLICT (
                    deployment_namespace, source_session_id, idempotency_key_hash
                ) DO NOTHING
                RETURNING *
                """,
                (
                    namespace,
                    uuid4(),
                    request.source_session_id,
                    uuid4(),
                    uuid4(),
                    idempotency_hash,
                    request_hash,
                    expected_source_stream_version,
                    None if fence is None else fence.control_plane_epoch,
                    None if fence is None else fence.fencing_token,
                    None if fence is None else fence.owner_instance_id,
                    authority_revision,
                    Jsonb(workspace_revision.model_dump(mode="json")),
                    task_profile_revision,
                    effective_depth_limit,
                    now,
                    now,
                ),
            ).fetchone()
            if row is None:
                row = find_reservation(
                    connection,
                    namespace,
                    request.source_session_id,
                    idempotency_hash,
                )
                assert row is not None
                if row["request_hash"] != request_hash:
                    raise HandoffIdempotencyConflictError(
                        "handoff idempotency key reused with different request"
                    )
        return operation_from_row(row)

    def commit(self, request: SessionHandoffCommitRequest) -> SessionHandoffResult:
        try:
            with self._database.connect() as connection:
                return commit_handoff_in_transaction(
                    connection,
                    self._database.deployment_namespace,
                    request,
                )
        except HandoffStorageConflictError:
            raise
        except (errors.IntegrityError, ValueError) as error:
            raise HandoffStorageConflictError(
                "handoff aggregate commit conflicted with authoritative state"
            ) from error

    def abort(self, operation_id: str, *, code: str) -> HandoffOperation:
        if not code.strip():
            raise ValueError("handoff abort code must not be blank")
        namespace = self._database.deployment_namespace
        with self._database.connect() as connection:
            current = lock_operation(
                connection,
                namespace,
                operation_id,
            )
            if current.status is HandoffOperationStatus.ABORTED:
                return current
            authority = AdministrativeMutationCAS(
                deployment_namespace=namespace,
                session_id=current.source_session_id,
                expected_stream_revision=current.expected_source_stream_version,
            )
            return abort_authorized_in_transaction(
                connection,
                namespace,
                SessionHandoffAbortRequest(
                    operation=current,
                    authority=authority,
                    code=code,
                ),
            )

    def abort_authorized(self, request: SessionHandoffAbortRequest) -> HandoffOperation:
        if not request.code.strip():
            raise ValueError("handoff abort code must not be blank")
        namespace = self._database.deployment_namespace
        with self._database.connect() as connection:
            return abort_authorized_in_transaction(connection, namespace, request)

    def get_handoff(self, handoff_id: HandoffId) -> SessionHandoffResult | None:
        with self._database.connect() as connection:
            operation = connection.execute(
                """
                SELECT * FROM handoff_operations
                WHERE deployment_namespace = %s AND handoff_id = %s
                  AND status = 'committed'
                """,
                (self._database.deployment_namespace, handoff_id),
            ).fetchone()
            return (
                None
                if operation is None
                else result_for_operation(
                    connection,
                    self._database.deployment_namespace,
                    operation_from_row(operation),
                    replay=False,
                )
            )

    def get_envelope(self, handoff_id: HandoffId) -> SessionHandoffEnvelope | None:
        with self._database.connect() as connection:
            row = connection.execute(
                """
                SELECT envelope FROM session_handoff_envelopes
                WHERE deployment_namespace = %s AND handoff_id = %s
                """,
                (self._database.deployment_namespace, handoff_id),
            ).fetchone()
        return None if row is None else SessionHandoffEnvelope.model_validate(row["envelope"])

    def get_lineage(self, session_id: SessionId) -> tuple[SessionLineage, ...]:
        namespace = self._database.deployment_namespace
        with self._database.connect() as connection:
            try:
                root = root_for_session(connection, namespace, session_id)
            except PostgresAgentTaskConflictError:
                return ()
            rows = connection.execute(
                """
                SELECT segment.session_id, segment.predecessor_id, segment.segment_index,
                       received.payload ->> 'handoff_id' AS inbound_handoff_id
                FROM execution_segments segment
                LEFT JOIN session_events received
                  ON received.deployment_namespace = segment.deployment_namespace
                 AND received.session_id = segment.session_id
                 AND received.event_type = 'session_handoff_received'
                WHERE segment.deployment_namespace = %s AND segment.task_id = %s
                ORDER BY segment.segment_index
                """,
                (namespace, TaskId(UUID(str(root)))),
            ).fetchall()
        return tuple(
            SessionLineage(
                session_id=SessionId(row["session_id"]),
                root_session_id=root,
                parent_session_id=(
                    None
                    if row["predecessor_id"] is None
                    else SessionId(row["predecessor_id"])
                ),
                inbound_handoff_id=(
                    None
                    if row["inbound_handoff_id"] is None
                    else HandoffId(UUID(row["inbound_handoff_id"]))
                ),
                stage_index=row["segment_index"],
            )
            for row in rows
        )

    def rebuild_lineage_index(self) -> int:
        namespace = self._database.deployment_namespace
        with self._database.connect() as connection:
            rows = connection.execute(
                """
                SELECT DISTINCT COALESCE(
                    received.payload ->> 'root_session_id',
                    projection.session_id::text
                )::uuid AS root_session_id
                FROM session_projections projection
                LEFT JOIN session_events received
                  ON received.deployment_namespace = projection.deployment_namespace
                 AND received.session_id = projection.session_id
                 AND received.event_type = 'session_handoff_received'
                WHERE projection.deployment_namespace = %s
                """,
                (namespace,),
            ).fetchall()
            for row in rows:
                rebuild_task_in_transaction(
                    connection,
                    namespace,
                    SessionId(row["root_session_id"]),
                )
            return len(rows)

    def abort_stale_preparing(self, *, before: datetime) -> int:
        if before.tzinfo is None:
            raise ValueError("stale handoff cutoff must be timezone-aware")
        namespace = self._database.deployment_namespace
        with self._database.connect() as connection:
            rows = connection.execute(
                """
                SELECT * FROM handoff_operations
                WHERE deployment_namespace = %s AND status = 'preparing'
                  AND updated_at < %s
                FOR UPDATE SKIP LOCKED
                """,
                (namespace, before),
            ).fetchall()
            aborted = 0
            for row in rows:
                operation = operation_from_row(row)
                authority = AdministrativeMutationCAS(
                    deployment_namespace=namespace,
                    session_id=operation.source_session_id,
                    expected_stream_revision=operation.expected_source_stream_version,
                )
                try:
                    abort_authorized_in_transaction(
                        connection,
                        namespace,
                        SessionHandoffAbortRequest(
                            operation=operation,
                            authority=authority,
                            code="handoff_operation_stale",
                        ),
                    )
                except HandoffStorageConflictError:
                    continue
                aborted += 1
            return aborted

    def claim_dispatch(
        self,
        *,
        worker_id: str,
        claimed_at: datetime,
        lease_seconds: int = 60,
    ) -> HandoffDispatch | None:
        del worker_id, claimed_at, lease_seconds
        raise NotImplementedError("cloud dispatch requires the fenced dispatch Port")

    def acknowledge_dispatch(self, delivery_id: str, *, worker_id: str) -> None:
        del delivery_id, worker_id
        raise NotImplementedError("cloud dispatch requires the fenced dispatch Port")

def _require_sha256(value: str, *, field_name: str) -> None:
    if len(value) != 64 or any(character not in "0123456789abcdef" for character in value):
        raise ValueError(f"{field_name} must be a lowercase sha256 digest")
