"""Namespace-bound PostgreSQL Workspace Control Plane authority (v18)."""

from __future__ import annotations

from typing import Any
from uuid import UUID, uuid4

from agent_core.domain.workspace_control import (
    WorkspaceAction,
    WorkspaceId,
    WorkspaceInstance,
    WorkspaceLifecycleState,
    WorkspaceSource,
    WorkspaceSourceKind,
    next_workspace_state,
)
from agent_core.ports.workspace_control import (
    WorkspaceOperationReceipt,
    WorkspaceSnapshotRef,
)

from agent_storage.postgres.database import PostgresDatabase


class WorkspaceControlStorageError(ValueError):
    """Raised for invalid Workspace Control Plane storage inputs."""


class WorkspaceControlTransitionConflict(ValueError):
    """Raised when a CAS transition no longer matches the durable state."""


_SOURCE_KINDS = {
    WorkspaceSourceKind.GIT_REPOSITORY: "git_repository",
    WorkspaceSourceKind.UPLOADED_ARCHIVE: "uploaded_archive",
    WorkspaceSourceKind.DURABLE_SNAPSHOT: "durable_snapshot",
    WorkspaceSourceKind.HOST_REFERENCE: "host_reference",
}

_READY_STATES = {WorkspaceLifecycleState.READY, WorkspaceLifecycleState.SEALED}


class PostgresWorkspaceControlStore:
    """Owns the authoritative workspace lifecycle; transitions are CAS."""

    def __init__(self, dsn: str, *, deployment_namespace: str) -> None:
        self._database = PostgresDatabase(dsn, deployment_namespace=deployment_namespace)

    @property
    def deployment_namespace(self) -> str:
        return self._database.deployment_namespace

    def create_pending(
        self,
        source: WorkspaceSource,
        *,
        workspace_id: WorkspaceId,
        quota_bytes: int,
        owner_session_id: UUID | None,
        idempotency_key: str,
    ) -> tuple[WorkspaceInstance, WorkspaceOperationReceipt]:
        namespace = self.deployment_namespace
        with self._database.connect() as connection:
            existing = connection.execute(
                """
                SELECT workspace_id FROM workspace_control_operations
                WHERE deployment_namespace = %s AND idempotency_key = %s
                """,
                (namespace, idempotency_key),
            ).fetchone()
            if existing is not None:
                instance = self._require_instance(connection, WorkspaceId(existing["workspace_id"]))
                return instance, WorkspaceOperationReceipt(
                    workspace_id=instance.workspace_id,
                    operation_id=uuid4(),
                    resulting_state=instance.state,
                    idempotent_replay=True,
                )
            connection.execute(
                """
                INSERT INTO workspace_control_instances (
                    deployment_namespace, workspace_id, source_kind,
                    source_locator, source_pinned_revision, source_archive_uri,
                    source_content_digest, state, quota_bytes, owner_session_id,
                    provision_operation_id
                ) VALUES (%s, %s, %s, %s, %s, %s, %s, 'pending', %s, %s, %s)
                """,
                (
                    namespace,
                    workspace_id,
                    _SOURCE_KINDS[source.kind],
                    source.locator,
                    source.pinned_revision,
                    source.archive_artifact_uri,
                    source.content_digest,
                    quota_bytes,
                    owner_session_id,
                    uuid4(),
                ),
            )
            receipt = self._append_operation(
                connection,
                workspace_id,
                action="create_pending",
                idempotency_key=idempotency_key,
                resulting_state=WorkspaceLifecycleState.PENDING,
            )
            instance = self._require_instance(connection, workspace_id)
        return instance, receipt

    def transition(
        self,
        workspace_id: WorkspaceId,
        action: WorkspaceAction,
        *,
        materialized_revision: str | None = None,
        content_digest: str | None = None,
        volume_ref: str | None = None,
    ) -> tuple[WorkspaceInstance, WorkspaceOperationReceipt]:
        target = next_workspace_state  # keep the domain table authoritative
        with self._database.connect() as connection:
            current = self._require_instance(connection, workspace_id)
            next_state = target(current.state, action)
            assignments: list[str] = ["state = %s", "updated_at = transaction_timestamp()"]
            values: list[Any] = [next_state.value]
            if materialized_revision is not None:
                assignments.append("materialized_revision = %s")
                values.append(materialized_revision)
            if content_digest is not None:
                assignments.append("content_digest = %s")
                values.append(content_digest)
            if volume_ref is not None:
                assignments.append("volume_ref = %s")
                values.append(volume_ref)
            updated = connection.execute(
                f"""
                UPDATE workspace_control_instances
                SET {", ".join(assignments)}
                WHERE deployment_namespace = %s AND workspace_id = %s AND state = %s
                RETURNING workspace_id
                """,
                (*values, self.deployment_namespace, workspace_id, current.state.value),
            ).fetchone()
            if updated is None:
                raise WorkspaceControlTransitionConflict(
                    "workspace state changed concurrently; retry from the durable state"
                )
            receipt = self._append_operation(
                connection,
                workspace_id,
                action=action.value,
                idempotency_key=f"transition:{workspace_id}:{action.value}:{uuid4()}",
                resulting_state=next_state,
            )
            instance = self._require_instance(connection, workspace_id)
        return instance, receipt

    def get(self, workspace_id: WorkspaceId) -> WorkspaceInstance | None:
        with self._database.connect() as connection:
            row = self._fetch_instance(connection, workspace_id)
        return _row_to_instance(row, self.deployment_namespace) if row is not None else None

    def list_uncertain(self, *, limit: int = 100) -> tuple[WorkspaceInstance, ...]:
        with self._database.connect() as connection:
            rows = connection.execute(
                """
                SELECT * FROM workspace_control_instances
                WHERE deployment_namespace = %s AND state = 'uncertain'
                ORDER BY updated_at ASC LIMIT %s
                """,
                (self.deployment_namespace, max(1, limit)),
            ).fetchall()
        return tuple(_row_to_instance(row, self.deployment_namespace) for row in rows)

    def record_snapshot(self, snapshot: WorkspaceSnapshotRef) -> WorkspaceSnapshotRef:
        with self._database.connect() as connection:
            connection.execute(
                """
                INSERT INTO workspace_control_snapshots (
                    deployment_namespace, snapshot_id, workspace_id,
                    materialized_revision, content_digest, object_uri
                ) VALUES (%s, %s, %s, %s, %s, %s)
                """,
                (
                    self.deployment_namespace,
                    snapshot.snapshot_id,
                    snapshot.workspace_id,
                    snapshot.materialized_revision,
                    snapshot.content_digest,
                    snapshot.object_uri,
                ),
            )
        return snapshot

    def list_snapshots(self, workspace_id: WorkspaceId) -> tuple[WorkspaceSnapshotRef, ...]:
        with self._database.connect() as connection:
            rows = connection.execute(
                """
                SELECT snapshot_id, workspace_id, materialized_revision,
                       content_digest, object_uri
                FROM workspace_control_snapshots
                WHERE deployment_namespace = %s AND workspace_id = %s
                ORDER BY created_at ASC
                """,
                (self.deployment_namespace, workspace_id),
            ).fetchall()
        return tuple(
            WorkspaceSnapshotRef(
                snapshot_id=row["snapshot_id"],
                workspace_id=row["workspace_id"],
                materialized_revision=row["materialized_revision"],
                content_digest=row["content_digest"],
                object_uri=row["object_uri"],
            )
            for row in rows
        )

    def _append_operation(
        self,
        connection: Any,
        workspace_id: WorkspaceId,
        *,
        action: str,
        idempotency_key: str,
        resulting_state: WorkspaceLifecycleState,
    ) -> WorkspaceOperationReceipt:
        operation_id = uuid4()
        connection.execute(
            """
            INSERT INTO workspace_control_operations (
                deployment_namespace, operation_id, workspace_id, action,
                idempotency_key, resulting_state
            ) VALUES (%s, %s, %s, %s, %s, %s)
            """,
            (
                self.deployment_namespace,
                operation_id,
                workspace_id,
                action,
                idempotency_key,
                resulting_state.value,
            ),
        )
        return WorkspaceOperationReceipt(
            workspace_id=workspace_id,
            operation_id=operation_id,
            resulting_state=resulting_state,
        )

    def _require_instance(self, connection: Any, workspace_id: WorkspaceId) -> WorkspaceInstance:
        row = self._fetch_instance(connection, workspace_id)
        if row is None:
            raise WorkspaceControlStorageError(
                "workspace instance is missing in this deployment namespace"
            )
        return _row_to_instance(row, self.deployment_namespace)

    def _fetch_instance(self, connection: Any, workspace_id: WorkspaceId) -> Any:
        return connection.execute(
            """
            SELECT workspace_id, source_kind, source_locator, source_pinned_revision,
                   source_archive_uri, source_content_digest, state,
                   materialized_revision, content_digest, volume_ref,
                   owner_session_id, quota_bytes
            FROM workspace_control_instances
            WHERE deployment_namespace = %s AND workspace_id = %s
            """,
            (self.deployment_namespace, workspace_id),
        ).fetchone()


def _row_to_instance(row: dict[str, Any], deployment_namespace: str) -> WorkspaceInstance:
    source = WorkspaceSource(
        kind=WorkspaceSourceKind(row["source_kind"]),
        locator=row["source_locator"],
        pinned_revision=row["source_pinned_revision"],
        archive_artifact_uri=row["source_archive_uri"],
        content_digest=row["source_content_digest"],
    )
    return WorkspaceInstance(
        workspace_id=WorkspaceId(row["workspace_id"]),
        deployment_namespace=deployment_namespace,
        source=source,
        state=WorkspaceLifecycleState(row["state"]),
        materialized_revision=row["materialized_revision"],
        content_digest=row["content_digest"],
        volume_ref=row["volume_ref"],
        owner_session_id=row["owner_session_id"],
        quota_bytes=row["quota_bytes"],
    )
