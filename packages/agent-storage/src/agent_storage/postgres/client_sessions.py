"""PostgreSQL adapter for client sessions, mounts, bindings and leases.

One active controller lease per (task, run) is enforced by the primary
key; fence checks compare hashes only — token values never persist
(ADR-CLIENT-01).
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from agent_core.domain.client_capabilities import (
    MountedCapabilityNarrowingError,
    MountedCapabilitySnapshot,
)
from agent_core.domain.client_run_bindings import (
    ClientBindingNarrowingError,
    ClientRunBinding,
)
from agent_core.domain.client_sessions import (
    ClientSession,
    ClientSessionError,
    ClientSessionExpiredError,
    ClientSessionGrant,
    ClientSessionStatus,
)
from agent_core.domain.identifiers import (
    ClientRunBindingId,
    ClientSessionId,
    SessionId,
    TaskId,
)
from agent_core.ports.client_session_registry import ClientSessionRegistryPort
from psycopg.types.json import Jsonb

from agent_storage.postgres.client_control_leases import (
    PostgresClientControlLeaseStore as PostgresClientControlLeaseStore,
)
from agent_storage.postgres.database import PostgresDatabase


class PostgresClientSessionRegistry(ClientSessionRegistryPort):
    def __init__(self, dsn: str, *, deployment_namespace: str) -> None:
        self._database = PostgresDatabase(dsn, deployment_namespace=deployment_namespace)
        self._namespace = self._database.deployment_namespace

    def create_session(self, session: ClientSession) -> None:
        with self._database.connect() as connection:
            inserted = connection.execute(
                """
                INSERT INTO client_sessions (
                    deployment_namespace, client_session_id, host_app_id,
                    namespace_id, frontend_app_id, origin, user_ref,
                    profile_digest, credential_hash, grant_json, status, ui_revision,
                    mounted_snapshot_digest, created_at, heartbeat_at, expires_at
                ) VALUES (
                    %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s
                )
                ON CONFLICT (deployment_namespace, client_session_id) DO NOTHING
                RETURNING client_session_id
                """,
                (
                    self._namespace,
                    session.session_id,
                    session.grant.host_app_id,
                    session.grant.namespace_id,
                    session.grant.frontend_app_id,
                    session.grant.origin,
                    session.grant.user_ref,
                    session.grant.profile_digest,
                    session.credential_hash,
                    Jsonb(session.grant.model_dump(mode="json")),
                    session.status.value,
                    session.ui_revision,
                    session.mounted_snapshot_digest,
                    session.created_at,
                    session.heartbeat_at,
                    session.expires_at,
                ),
            ).fetchone()
            if inserted is None:
                existing = self._select_session(connection, session.session_id)
                if existing is None or _session_from_row(existing) != session:
                    raise ClientSessionError(
                        "client session identity already has different content"
                    )

    def get_session(self, session_id: ClientSessionId) -> ClientSession | None:
        with self._database.connect() as connection:
            row = self._select_session(connection, session_id)
        return None if row is None else _session_from_row(row)

    def heartbeat_session(
        self, session_id: ClientSessionId, *, heartbeat_at: datetime
    ) -> ClientSession:
        expired = False
        with self._database.connect() as connection:
            row = self._select_session(connection, session_id)
            if row is None:
                raise ClientSessionExpiredError("client session not found")
            session = _session_from_row(row)
            expired = (
                session.status is not ClientSessionStatus.ACTIVE
                or heartbeat_at >= session.expires_at
            )
            if expired:
                connection.execute(
                    """
                    UPDATE client_sessions SET status = 'expired'
                    WHERE deployment_namespace = %s AND client_session_id = %s
                        AND status = 'active' AND expires_at <= %s
                    """,
                    (self._namespace, session_id, heartbeat_at),
                )
            else:
                connection.execute(
                    """
                    UPDATE client_sessions SET heartbeat_at = %s
                    WHERE deployment_namespace = %s AND client_session_id = %s
                    """,
                    (heartbeat_at, self._namespace, session_id),
                )
        if expired:
            raise ClientSessionExpiredError("client session cannot heartbeat")
        return session.model_copy(update={"heartbeat_at": heartbeat_at})

    def close_session(self, session_id: ClientSessionId) -> None:
        with self._database.connect() as connection:
            connection.execute(
                """
                UPDATE client_sessions
                SET status = 'closed'
                WHERE deployment_namespace = %s AND client_session_id = %s
                """,
                (self._namespace, session_id),
            )

    def save_mounted_snapshot(self, snapshot: MountedCapabilitySnapshot) -> None:
        with self._database.connect() as connection:
            saved = connection.execute(
                """
                INSERT INTO client_mounted_capability_snapshots (
                    deployment_namespace, client_session_id, snapshot_digest,
                    snapshot_json, ui_revision, mounted_at
                ) VALUES (%s, %s, %s, %s, %s, %s)
                ON CONFLICT (deployment_namespace, client_session_id)
                DO UPDATE SET
                    snapshot_digest = EXCLUDED.snapshot_digest,
                    snapshot_json = EXCLUDED.snapshot_json,
                    ui_revision = EXCLUDED.ui_revision,
                    mounted_at = EXCLUDED.mounted_at
                WHERE client_mounted_capability_snapshots.ui_revision
                          < EXCLUDED.ui_revision
                   OR client_mounted_capability_snapshots.snapshot_digest
                          = EXCLUDED.snapshot_digest
                RETURNING client_session_id
                """,
                (
                    self._namespace,
                    snapshot.client_session_id,
                    snapshot.snapshot_digest,
                    Jsonb(snapshot.model_dump(mode="json")),
                    snapshot.ui_revision,
                    snapshot.mounted_at,
                ),
            ).fetchone()
            if saved is None:
                raise MountedCapabilityNarrowingError(
                    "stale or conflicting mount revision rejected"
                )
            updated = connection.execute(
                """
                UPDATE client_sessions
                SET mounted_snapshot_digest = %s, ui_revision = %s
                WHERE deployment_namespace = %s AND client_session_id = %s
                    AND ui_revision <= %s
                RETURNING client_session_id
                """,
                (
                    snapshot.snapshot_digest,
                    snapshot.ui_revision,
                    self._namespace,
                    snapshot.client_session_id,
                    snapshot.ui_revision,
                ),
            ).fetchone()
            if updated is None:
                raise MountedCapabilityNarrowingError(
                    "client session is absent or ahead of the mount revision"
                )

    def get_mounted_snapshot(
        self, client_session_id: ClientSessionId
    ) -> MountedCapabilitySnapshot | None:
        with self._database.connect() as connection:
            row = connection.execute(
                """
                SELECT snapshot_json FROM client_mounted_capability_snapshots
                WHERE deployment_namespace = %s AND client_session_id = %s
                """,
                (self._namespace, client_session_id),
            ).fetchone()
        if row is None:
            return None
        return MountedCapabilitySnapshot.model_validate(row["snapshot_json"])

    def save_run_binding(self, binding: ClientRunBinding) -> None:
        with self._database.connect() as connection:
            existing = connection.execute(
                """
                SELECT * FROM client_run_bindings
                WHERE deployment_namespace = %s AND task_id = %s
                    AND run_id = %s AND client_session_id = %s
                FOR UPDATE
                """,
                (
                    self._namespace,
                    binding.task_id,
                    binding.run_id,
                    binding.client_session_id,
                ),
            ).fetchone()
            if existing is not None:
                current = int(existing["binding_revision"])
                if binding.binding_revision == current:
                    if _binding_from_row(existing) == binding:
                        return
                    raise ClientBindingNarrowingError(
                        "the same binding revision has different content"
                    )
                if binding.binding_revision != current + 1:
                    raise ClientBindingNarrowingError("binding revisions must advance exactly once")
                prior = _binding_from_row(existing)
                if (
                    prior.profile_digest != binding.profile_digest
                    or prior.task_capability_scope != binding.task_capability_scope
                    or set(binding.allowed_actions) - set(prior.allowed_actions)
                ):
                    raise ClientBindingNarrowingError(
                        "binding updates may only narrow existing actions"
                    )
            saved = connection.execute(
                """
                INSERT INTO client_run_bindings (
                    deployment_namespace, binding_id, task_id, run_id,
                    client_session_id, profile_digest, mounted_snapshot_digest,
                    task_capability_scope, allowed_actions, binding_revision,
                    created_at
                ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                ON CONFLICT (deployment_namespace, task_id, run_id, client_session_id)
                DO UPDATE SET
                    allowed_actions = EXCLUDED.allowed_actions,
                    mounted_snapshot_digest = EXCLUDED.mounted_snapshot_digest,
                    binding_revision = EXCLUDED.binding_revision
                WHERE client_run_bindings.binding_revision
                      = EXCLUDED.binding_revision - 1
                RETURNING binding_id
                """,
                (
                    self._namespace,
                    binding.binding_id,
                    binding.task_id,
                    binding.run_id,
                    binding.client_session_id,
                    binding.profile_digest,
                    binding.mounted_snapshot_digest,
                    Jsonb(list(binding.task_capability_scope)),
                    Jsonb(list(binding.allowed_actions)),
                    binding.binding_revision,
                    binding.created_at,
                ),
            ).fetchone()
            if saved is None:
                raise ClientBindingNarrowingError("concurrent binding revision update rejected")

    def get_run_binding(
        self, task_id: TaskId, run_id: str, client_session_id: ClientSessionId
    ) -> ClientRunBinding | None:
        with self._database.connect() as connection:
            row = connection.execute(
                """
                SELECT * FROM client_run_bindings
                WHERE deployment_namespace = %s AND task_id = %s
                    AND run_id = %s AND client_session_id = %s
                """,
                (self._namespace, task_id, run_id, client_session_id),
            ).fetchone()
        if row is None:
            return None
        return _binding_from_row(row)

    def get_active_run_binding(self, execution_session_id: SessionId) -> ClientRunBinding | None:
        with self._database.connect() as connection:
            rows = connection.execute(
                """
                SELECT binding.* FROM client_run_bindings AS binding
                JOIN agent_tasks AS task
                  ON task.deployment_namespace = binding.deployment_namespace
                 AND task.task_id = binding.task_id
                JOIN client_control_leases AS lease
                  ON lease.deployment_namespace = binding.deployment_namespace
                 AND lease.task_id = binding.task_id
                 AND lease.run_id = binding.run_id
                 AND lease.client_session_id = binding.client_session_id
                WHERE binding.deployment_namespace = %s
                  AND task.active_segment_id = %s
                  AND lease.released_at IS NULL AND lease.expires_at > %s
                ORDER BY lease.acquired_at DESC
                LIMIT 2
                """,
                (self._namespace, execution_session_id, datetime.now(UTC)),
            ).fetchall()
        return _binding_from_row(rows[0]) if len(rows) == 1 else None

    def _select_session(self, connection: Any, session_id: ClientSessionId) -> Any:
        return connection.execute(
            """
            SELECT * FROM client_sessions
            WHERE deployment_namespace = %s AND client_session_id = %s
            """,
            (self._namespace, session_id),
        ).fetchone()


def _session_from_row(row: Any) -> ClientSession:
    return ClientSession(
        session_id=ClientSessionId(UUID(str(row["client_session_id"]))),
        grant=ClientSessionGrant.model_validate(row["grant_json"]),
        credential_hash=row["credential_hash"],
        status=ClientSessionStatus(row["status"]),
        created_at=row["created_at"],
        heartbeat_at=row["heartbeat_at"],
        expires_at=row["expires_at"],
        mounted_snapshot_digest=row["mounted_snapshot_digest"],
        ui_revision=int(row["ui_revision"]),
    )


def _binding_from_row(row: Any) -> ClientRunBinding:
    return ClientRunBinding(
        binding_id=ClientRunBindingId(UUID(str(row["binding_id"]))),
        task_id=TaskId(UUID(str(row["task_id"]))),
        run_id=row["run_id"],
        client_session_id=ClientSessionId(UUID(str(row["client_session_id"]))),
        profile_digest=row["profile_digest"],
        mounted_snapshot_digest=row["mounted_snapshot_digest"],
        task_capability_scope=tuple(row["task_capability_scope"]),
        allowed_actions=tuple(row["allowed_actions"]),
        binding_revision=int(row["binding_revision"]),
        created_at=row["created_at"],
    )
