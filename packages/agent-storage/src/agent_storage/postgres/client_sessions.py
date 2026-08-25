"""PostgreSQL adapter for client sessions, mounts, bindings and leases.

One active controller lease per (task, run) is enforced by the primary
key; fence checks compare hashes only — token values never persist
(ADR-CLIENT-01).
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID

from agent_core.domain.client_capabilities import MountedCapabilitySnapshot
from agent_core.domain.client_run_bindings import ClientRunBinding
from agent_core.domain.client_sessions import (
    ClientControlFence,
    ClientControlLease,
    ClientControlLeaseError,
    ClientFenceError,
    ClientSession,
    ClientSessionExpiredError,
    ClientSessionGrant,
    ClientSessionStatus,
)
from agent_core.domain.identifiers import (
    ClientRunBindingId,
    ClientSessionId,
    TaskId,
)
from agent_core.ports.client_control_lease import ClientControlLeasePort
from agent_core.ports.client_session_registry import ClientSessionRegistryPort
from psycopg.types.json import Jsonb

from agent_storage.postgres.database import PostgresDatabase


class PostgresClientSessionRegistry(ClientSessionRegistryPort):
    def __init__(self, dsn: str, *, deployment_namespace: str) -> None:
        self._database = PostgresDatabase(dsn, deployment_namespace=deployment_namespace)
        self._namespace = self._database.deployment_namespace

    def create_session(self, session: ClientSession) -> None:
        with self._database.connect() as connection:
            connection.execute(
                """
                INSERT INTO client_sessions (
                    deployment_namespace, client_session_id, host_app_id,
                    namespace_id, frontend_app_id, origin, user_ref,
                    profile_digest, grant_json, status, ui_revision,
                    mounted_snapshot_digest, created_at, heartbeat_at, expires_at
                ) VALUES (
                    %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s
                )
                ON CONFLICT (deployment_namespace, client_session_id) DO NOTHING
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
                    Jsonb(session.grant.model_dump(mode="json")),
                    session.status.value,
                    session.ui_revision,
                    session.mounted_snapshot_digest,
                    session.created_at,
                    session.heartbeat_at,
                    session.expires_at,
                ),
            )

    def get_session(self, session_id: ClientSessionId) -> ClientSession | None:
        with self._database.connect() as connection:
            row = self._select_session(connection, session_id)
        return None if row is None else _session_from_row(row)

    def heartbeat_session(
        self, session_id: ClientSessionId, *, heartbeat_at: datetime
    ) -> ClientSession:
        with self._database.connect() as connection:
            row = self._select_session(connection, session_id)
            if row is None:
                raise ClientSessionExpiredError("client session not found")
            session = _session_from_row(row)
            session.ensure_renewable(now=heartbeat_at)
            connection.execute(
                """
                UPDATE client_sessions
                SET heartbeat_at = %s,
                    status = CASE
                        WHEN %s >= expires_at THEN 'expired' ELSE status
                    END
                WHERE deployment_namespace = %s AND client_session_id = %s
                """,
                (heartbeat_at, heartbeat_at, self._namespace, session_id),
            )
        return session

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
            connection.execute(
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
                """,
                (
                    self._namespace,
                    snapshot.client_session_id,
                    snapshot.snapshot_digest,
                    Jsonb(snapshot.model_dump(mode="json")),
                    snapshot.ui_revision,
                    snapshot.mounted_at,
                ),
            )
            connection.execute(
                """
                UPDATE client_sessions
                SET mounted_snapshot_digest = %s, ui_revision = %s
                WHERE deployment_namespace = %s AND client_session_id = %s
                """,
                (
                    snapshot.snapshot_digest,
                    snapshot.ui_revision,
                    self._namespace,
                    snapshot.client_session_id,
                ),
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
                SELECT binding_revision FROM client_run_bindings
                WHERE deployment_namespace = %s AND task_id = %s
                    AND run_id = %s AND client_session_id = %s
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
                if binding.binding_revision < current:
                    raise ClientControlLeaseError(
                        "binding revisions may only increase"
                    )
                if binding.binding_revision == current:
                    return  # idempotent replay
            connection.execute(
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
            )

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

    def _select_session(self, connection: Any, session_id: ClientSessionId) -> Any:
        return connection.execute(
            """
            SELECT * FROM client_sessions
            WHERE deployment_namespace = %s AND client_session_id = %s
            """,
            (self._namespace, session_id),
        ).fetchone()


class PostgresClientControlLeaseStore(ClientControlLeasePort):
    def __init__(self, dsn: str, *, deployment_namespace: str) -> None:
        self._database = PostgresDatabase(dsn, deployment_namespace=deployment_namespace)
        self._namespace = self._database.deployment_namespace

    def claim_controller(
        self,
        run_binding_id: UUID,
        *,
        task_id: TaskId,
        run_id: str,
        client_session_id: ClientSessionId,
        fence: ClientControlFence,
        ttl: timedelta,
    ) -> ClientControlLease:
        now = datetime.now(UTC)
        expires_at = now + ttl
        with self._database.connect() as connection:
            row = connection.execute(
                """
                INSERT INTO client_control_leases (
                    deployment_namespace, task_id, run_id, run_binding_id,
                    client_session_id, role, fence_hash,
                    acquired_at, heartbeat_at, expires_at
                ) VALUES (%s, %s, %s, %s, %s, 'controller', %s, %s, %s, %s)
                ON CONFLICT (deployment_namespace, task_id, run_id) DO UPDATE SET
                    run_binding_id = EXCLUDED.run_binding_id,
                    client_session_id = EXCLUDED.client_session_id,
                    fence_hash = EXCLUDED.fence_hash,
                    acquired_at = EXCLUDED.acquired_at,
                    heartbeat_at = EXCLUDED.heartbeat_at,
                    expires_at = EXCLUDED.expires_at,
                    released_at = NULL
                WHERE client_control_leases.released_at IS NOT NULL
                   OR client_control_leases.expires_at <= %s
                   OR client_control_leases.client_session_id = EXCLUDED.client_session_id
                RETURNING client_session_id, fence_hash, acquired_at,
                          heartbeat_at, expires_at
                """,
                (
                    self._namespace,
                    task_id,
                    run_id,
                    run_binding_id,
                    client_session_id,
                    fence.fence_hash,
                    now,
                    now,
                    expires_at,
                    now,
                ),
            ).fetchone()
            if row is None:
                holder = connection.execute(
                    """
                    SELECT client_session_id FROM client_control_leases
                    WHERE deployment_namespace = %s AND task_id = %s AND run_id = %s
                    """,
                    (self._namespace, task_id, run_id),
                ).fetchone()
                raise ClientControlLeaseError(
                    "another tab holds the active controller lease"
                    if holder is not None
                    else "controller lease claim failed"
                )
        return ClientControlLease(
            run_binding_id=run_binding_id,
            client_session_id=ClientSessionId(UUID(str(row["client_session_id"]))),
            fence_hash=row["fence_hash"],
            acquired_at=row["acquired_at"],
            heartbeat_at=row["heartbeat_at"],
            expires_at=row["expires_at"],
        )

    def renew(
        self,
        run_binding_id: UUID,
        *,
        task_id: TaskId,
        run_id: str,
        fence: ClientControlFence,
        ttl: timedelta,
    ) -> ClientControlLease:
        now = datetime.now(UTC)
        expires_at = now + ttl
        with self._database.connect() as connection:
            row = connection.execute(
                """
                UPDATE client_control_leases
                SET heartbeat_at = %s, expires_at = %s
                WHERE deployment_namespace = %s AND task_id = %s AND run_id = %s
                    AND fence_hash = %s AND released_at IS NULL
                RETURNING client_session_id, fence_hash, acquired_at,
                          heartbeat_at, expires_at
                """,
                (
                    now,
                    expires_at,
                    self._namespace,
                    task_id,
                    run_id,
                    fence.fence_hash,
                ),
            ).fetchone()
            if row is None:
                raise ClientFenceError("stale client fence rejected on renew")
        return ClientControlLease(
            run_binding_id=run_binding_id,
            client_session_id=ClientSessionId(UUID(str(row["client_session_id"]))),
            fence_hash=row["fence_hash"],
            acquired_at=row["acquired_at"],
            heartbeat_at=row["heartbeat_at"],
            expires_at=row["expires_at"],
        )

    def release(
        self,
        run_binding_id: UUID,
        *,
        task_id: TaskId,
        run_id: str,
        fence: ClientControlFence,
    ) -> None:
        with self._database.connect() as connection:
            row = connection.execute(
                """
                UPDATE client_control_leases
                SET released_at = NOW()
                WHERE deployment_namespace = %s AND task_id = %s AND run_id = %s
                    AND fence_hash = %s AND released_at IS NULL
                RETURNING task_id
                """,
                (self._namespace, task_id, run_id, fence.fence_hash),
            ).fetchone()
            if row is None:
                raise ClientFenceError("stale client fence rejected on release")

    def get_active(self, run_binding_id: UUID) -> ClientControlLease | None:
        with self._database.connect() as connection:
            row = connection.execute(
                """
                SELECT run_binding_id, client_session_id, fence_hash,
                       acquired_at, heartbeat_at, expires_at
                FROM client_control_leases
                WHERE deployment_namespace = %s AND run_binding_id = %s
                    AND released_at IS NULL
                """,
                (self._namespace, run_binding_id),
            ).fetchone()
        if row is None:
            return None
        return ClientControlLease(
            run_binding_id=row["run_binding_id"],
            client_session_id=ClientSessionId(UUID(str(row["client_session_id"]))),
            fence_hash=row["fence_hash"],
            acquired_at=row["acquired_at"],
            heartbeat_at=row["heartbeat_at"],
            expires_at=row["expires_at"],
        )


def _session_from_row(row: Any) -> ClientSession:
    return ClientSession(
        session_id=ClientSessionId(UUID(str(row["client_session_id"]))),
        grant=ClientSessionGrant.model_validate(row["grant_json"]),
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
