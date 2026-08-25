"""PostgreSQL controller leases for Client Run Bindings."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID

from agent_core.domain.client_sessions import (
    ClientControlFence,
    ClientControlLease,
    ClientControlLeaseError,
    ClientFenceError,
)
from agent_core.domain.identifiers import ClientSessionId, TaskId
from agent_core.ports.client_control_lease import ClientControlLeasePort

from agent_storage.postgres.database import PostgresDatabase


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
        if ttl <= timedelta(0):
            raise ValueError("controller lease TTL must be positive")
        now = datetime.now(UTC)
        expires_at = now + ttl
        with self._database.connect() as connection:
            binding = connection.execute(
                """
                SELECT binding_id FROM client_run_bindings
                WHERE deployment_namespace = %s AND binding_id = %s
                    AND task_id = %s AND run_id = %s AND client_session_id = %s
                """,
                (
                    self._namespace,
                    run_binding_id,
                    task_id,
                    run_id,
                    client_session_id,
                ),
            ).fetchone()
            if binding is None:
                raise ClientControlLeaseError(
                    "controller lease requires the exact persisted run binding"
                )
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
        return _lease_from_row(run_binding_id, row)

    def renew(
        self,
        run_binding_id: UUID,
        *,
        task_id: TaskId,
        run_id: str,
        fence: ClientControlFence,
        ttl: timedelta,
    ) -> ClientControlLease:
        if ttl <= timedelta(0):
            raise ValueError("controller lease TTL must be positive")
        now = datetime.now(UTC)
        expires_at = now + ttl
        with self._database.connect() as connection:
            row = connection.execute(
                """
                UPDATE client_control_leases
                SET heartbeat_at = %s, expires_at = %s
                WHERE deployment_namespace = %s AND task_id = %s AND run_id = %s
                    AND run_binding_id = %s AND fence_hash = %s AND released_at IS NULL
                    AND expires_at > %s
                RETURNING client_session_id, fence_hash, acquired_at,
                          heartbeat_at, expires_at
                """,
                (
                    now,
                    expires_at,
                    self._namespace,
                    task_id,
                    run_id,
                    run_binding_id,
                    fence.fence_hash,
                    now,
                ),
            ).fetchone()
            if row is None:
                raise ClientFenceError("stale client fence rejected on renew")
        return _lease_from_row(run_binding_id, row)

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
                    AND run_binding_id = %s AND fence_hash = %s AND released_at IS NULL
                RETURNING task_id
                """,
                (
                    self._namespace,
                    task_id,
                    run_id,
                    run_binding_id,
                    fence.fence_hash,
                ),
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
                    AND released_at IS NULL AND expires_at > %s
                """,
                (self._namespace, run_binding_id, datetime.now(UTC)),
            ).fetchone()
        return None if row is None else _lease_from_row(run_binding_id, row)


def _lease_from_row(run_binding_id: UUID, row: Any) -> ClientControlLease:
    return ClientControlLease(
        run_binding_id=run_binding_id,
        client_session_id=ClientSessionId(UUID(str(row["client_session_id"]))),
        fence_hash=row["fence_hash"],
        acquired_at=row["acquired_at"],
        heartbeat_at=row["heartbeat_at"],
        expires_at=row["expires_at"],
    )
