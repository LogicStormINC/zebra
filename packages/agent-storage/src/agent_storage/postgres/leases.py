"""PostgreSQL Lease Store using database time and full-fence CAS."""

from datetime import timedelta
from typing import Any, NoReturn
from uuid import UUID

from agent_core.domain.identifiers import SessionId
from agent_core.domain.leases import (
    DEFAULT_MAX_LEASE_TTL,
    LeaseCheckpointRegressionError,
    LeaseConflictError,
    LeaseFence,
    LeaseLostError,
    WorkerLease,
)
from agent_core.ports.lease_store import LeaseStorePort

from agent_storage.postgres.database import PostgresDatabase
from agent_storage.postgres.epoch import PostgresControlPlaneEpochError


class PostgresLeaseStore(LeaseStorePort):
    def __init__(
        self,
        dsn: str,
        *,
        deployment_namespace: str,
        maximum_ttl: timedelta = DEFAULT_MAX_LEASE_TTL,
    ) -> None:
        if maximum_ttl <= timedelta(0):
            raise ValueError("maximum lease ttl must be positive")
        self._database = PostgresDatabase(dsn, deployment_namespace=deployment_namespace)
        self._maximum_ttl = maximum_ttl

    def acquire(
        self,
        session_id: SessionId,
        *,
        owner_instance_id: str,
        ttl: timedelta,
        checkpoint: int | None = None,
    ) -> WorkerLease:
        validated_ttl = self._ttl(ttl)
        owner = self._owner_instance_id(owner_instance_id)
        requested_checkpoint = None if checkpoint is None else self._checkpoint(checkpoint)
        with self._database.connect() as connection:
            row = connection.execute(
                """
                WITH authority AS MATERIALIZED (
                    SELECT epoch, transaction_timestamp() AS database_now
                    FROM control_plane_epochs
                    WHERE deployment_namespace = %s
                    FOR SHARE
                )
                INSERT INTO worker_leases (
                    deployment_namespace, session_id, control_plane_epoch,
                    fencing_token, owner_instance_id, checkpoint,
                    acquired_at, heartbeat_at, expires_at, released_at
                )
                SELECT %s, %s, epoch, 1, %s, COALESCE(%s::bigint, 0),
                       database_now, database_now, database_now + %s::interval, NULL
                FROM authority
                ON CONFLICT (deployment_namespace, session_id) DO UPDATE SET
                    control_plane_epoch = EXCLUDED.control_plane_epoch,
                    fencing_token = worker_leases.fencing_token + 1,
                    owner_instance_id = EXCLUDED.owner_instance_id,
                    checkpoint = COALESCE(%s::bigint, worker_leases.checkpoint),
                    acquired_at = EXCLUDED.acquired_at,
                    heartbeat_at = EXCLUDED.heartbeat_at,
                    expires_at = EXCLUDED.expires_at,
                    released_at = NULL
                WHERE (
                    worker_leases.control_plane_epoch != EXCLUDED.control_plane_epoch
                    OR worker_leases.released_at IS NOT NULL
                    OR worker_leases.expires_at <= EXCLUDED.acquired_at
                )
                AND (%s::bigint IS NULL OR %s::bigint >= worker_leases.checkpoint)
                RETURNING *
                """,
                (
                    self._database.deployment_namespace,
                    self._database.deployment_namespace,
                    session_id,
                    owner,
                    requested_checkpoint,
                    validated_ttl,
                    requested_checkpoint,
                    requested_checkpoint,
                    requested_checkpoint,
                ),
            ).fetchone()
            if row is None:
                self._raise_acquire_failure(connection, session_id, requested_checkpoint)
        return _lease_from_row(row)

    def heartbeat(
        self,
        session_id: SessionId,
        *,
        fence: LeaseFence,
        ttl: timedelta,
        checkpoint: int,
    ) -> WorkerLease:
        validated_ttl = self._ttl(ttl)
        next_checkpoint = self._checkpoint(checkpoint)
        with self._database.connect() as connection:
            row = connection.execute(
                """
                WITH authority AS MATERIALIZED (
                    SELECT epoch FROM control_plane_epochs
                    WHERE deployment_namespace = %s
                    FOR SHARE
                )
                UPDATE worker_leases AS lease
                SET checkpoint = %s,
                    heartbeat_at = transaction_timestamp(),
                    expires_at = transaction_timestamp() + %s::interval
                FROM authority
                WHERE lease.deployment_namespace = %s
                  AND lease.session_id = %s
                  AND lease.control_plane_epoch = %s
                  AND lease.control_plane_epoch = authority.epoch
                  AND lease.fencing_token = %s
                  AND lease.owner_instance_id = %s
                  AND lease.released_at IS NULL
                  AND lease.expires_at > transaction_timestamp()
                  AND lease.checkpoint <= %s
                RETURNING lease.*
                """,
                (
                    self._database.deployment_namespace,
                    next_checkpoint,
                    validated_ttl,
                    self._database.deployment_namespace,
                    session_id,
                    fence.control_plane_epoch,
                    fence.fencing_token,
                    fence.owner_instance_id,
                    next_checkpoint,
                ),
            ).fetchone()
            if row is None:
                self._raise_heartbeat_failure(connection, session_id, fence, next_checkpoint)
        return _lease_from_row(row)

    def release(self, session_id: SessionId, *, fence: LeaseFence) -> None:
        with self._database.connect() as connection:
            row = connection.execute(
                """
                WITH authority AS MATERIALIZED (
                    SELECT epoch FROM control_plane_epochs
                    WHERE deployment_namespace = %s
                    FOR SHARE
                )
                UPDATE worker_leases AS lease
                SET released_at = transaction_timestamp()
                FROM authority
                WHERE lease.deployment_namespace = %s
                  AND lease.session_id = %s
                  AND lease.control_plane_epoch = %s
                  AND lease.control_plane_epoch = authority.epoch
                  AND lease.fencing_token = %s
                  AND lease.owner_instance_id = %s
                  AND lease.released_at IS NULL
                  AND lease.expires_at > transaction_timestamp()
                RETURNING lease.session_id
                """,
                (
                    self._database.deployment_namespace,
                    self._database.deployment_namespace,
                    session_id,
                    fence.control_plane_epoch,
                    fence.fencing_token,
                    fence.owner_instance_id,
                ),
            ).fetchone()
        if row is None:
            raise LeaseLostError("lease release rejected by the current fence")

    def get(self, session_id: SessionId) -> WorkerLease | None:
        with self._database.connect() as connection:
            row = connection.execute(
                """
                SELECT lease.* FROM worker_leases AS lease
                JOIN control_plane_epochs AS authority USING (deployment_namespace)
                WHERE lease.deployment_namespace = %s
                  AND lease.session_id = %s
                  AND lease.control_plane_epoch = authority.epoch
                  AND lease.released_at IS NULL
                  AND lease.expires_at > transaction_timestamp()
                """,
                (self._database.deployment_namespace, session_id),
            ).fetchone()
        return None if row is None else _lease_from_row(row)

    def _raise_acquire_failure(
        self,
        connection: Any,
        session_id: SessionId,
        checkpoint: int | None,
    ) -> NoReturn:
        row = connection.execute(
            """
            SELECT authority.epoch, lease.checkpoint,
                   lease.control_plane_epoch = authority.epoch
                   AND lease.released_at IS NULL
                   AND lease.expires_at > transaction_timestamp() AS is_active
            FROM control_plane_epochs AS authority
            LEFT JOIN worker_leases AS lease
              ON lease.deployment_namespace = authority.deployment_namespace
             AND lease.session_id = %s
            WHERE authority.deployment_namespace = %s
            """,
            (session_id, self._database.deployment_namespace),
        ).fetchone()
        if row is None:
            raise PostgresControlPlaneEpochError("control-plane epoch is not bootstrapped")
        if row["is_active"]:
            raise LeaseConflictError("session already has an active lease")
        if checkpoint is not None and row["checkpoint"] is not None:
            if checkpoint < row["checkpoint"]:
                raise LeaseCheckpointRegressionError("lease checkpoint must not move backwards")
        raise LeaseConflictError("lease acquisition rejected")

    def _raise_heartbeat_failure(
        self,
        connection: Any,
        session_id: SessionId,
        fence: LeaseFence,
        checkpoint: int,
    ) -> NoReturn:
        row = connection.execute(
            """
            SELECT lease.checkpoint
            FROM worker_leases AS lease
            JOIN control_plane_epochs AS authority USING (deployment_namespace)
            WHERE lease.deployment_namespace = %s
              AND lease.session_id = %s
              AND lease.control_plane_epoch = %s
              AND lease.control_plane_epoch = authority.epoch
              AND lease.fencing_token = %s
              AND lease.owner_instance_id = %s
              AND lease.released_at IS NULL
              AND lease.expires_at > transaction_timestamp()
            """,
            (
                self._database.deployment_namespace,
                session_id,
                fence.control_plane_epoch,
                fence.fencing_token,
                fence.owner_instance_id,
            ),
        ).fetchone()
        if row is not None and checkpoint < row["checkpoint"]:
            raise LeaseCheckpointRegressionError("lease checkpoint must not move backwards")
        raise LeaseLostError("lease heartbeat rejected by the current fence")

    def _ttl(self, ttl: timedelta) -> timedelta:
        if ttl <= timedelta(0):
            raise ValueError("lease ttl must be positive")
        if ttl > self._maximum_ttl:
            raise ValueError("lease ttl exceeds configured maximum")
        return ttl

    @staticmethod
    def _checkpoint(value: int) -> int:
        if value < 0:
            raise ValueError("lease checkpoint must not be negative")
        return value

    @staticmethod
    def _owner_instance_id(value: str) -> str:
        stripped = value.strip()
        if not stripped:
            raise ValueError("owner_instance_id must not be blank")
        return stripped


def _lease_from_row(row: dict[str, Any]) -> WorkerLease:
    return WorkerLease(
        session_id=SessionId(row["session_id"]),
        fence=LeaseFence(
            control_plane_epoch=UUID(str(row["control_plane_epoch"])),
            fencing_token=row["fencing_token"],
            owner_instance_id=row["owner_instance_id"],
        ),
        checkpoint=row["checkpoint"],
        acquired_at=row["acquired_at"],
        heartbeat_at=row["heartbeat_at"],
        expires_at=row["expires_at"],
    )


def assert_current_lease_fence(
    connection: Any,
    deployment_namespace: str,
    session_id: SessionId,
    fence: LeaseFence,
) -> None:
    """Lock the namespace authority and reject a stale Worker mutation."""
    authority = connection.execute(
        """
        SELECT epoch FROM control_plane_epochs
        WHERE deployment_namespace = %s
        FOR SHARE
        """,
        (deployment_namespace,),
    ).fetchone()
    if authority is None or authority["epoch"] != fence.control_plane_epoch:
        raise LeaseLostError("mutation rejected by the current lease fence")
    row = connection.execute(
        """
        SELECT session_id FROM worker_leases
        WHERE deployment_namespace = %s AND session_id = %s
          AND control_plane_epoch = %s AND fencing_token = %s
          AND owner_instance_id = %s AND released_at IS NULL
          AND expires_at > transaction_timestamp()
        FOR SHARE
        """,
        (
            deployment_namespace,
            session_id,
            fence.control_plane_epoch,
            fence.fencing_token,
            fence.owner_instance_id,
        ),
    ).fetchone()
    if row is None:
        raise LeaseLostError("mutation rejected by the current lease fence")
