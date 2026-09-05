"""PostgreSQL Lease Store using post-lock database time and full-fence CAS."""

from datetime import UTC, datetime, timedelta
from typing import Any
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
from psycopg import sql

from agent_storage.postgres.database import PostgresDatabase
from agent_storage.postgres.epoch import PostgresControlPlaneEpochError


class PostgresLeaseStore(LeaseStorePort):
    def __init__(
        self, dsn: str, *, deployment_namespace: str,
        maximum_ttl: timedelta = DEFAULT_MAX_LEASE_TTL,
    ) -> None:
        if maximum_ttl <= timedelta(0):
            raise ValueError("maximum lease ttl must be positive")
        self._database = PostgresDatabase(dsn, deployment_namespace=deployment_namespace)
        self._maximum_ttl = maximum_ttl

    def acquire(
        self, session_id: SessionId, *, owner_instance_id: str,
        ttl: timedelta, checkpoint: int | None = None,
    ) -> WorkerLease:
        validated_ttl = self._ttl(ttl)
        owner = self._owner_instance_id(owner_instance_id)
        requested = None if checkpoint is None else self._checkpoint(checkpoint)
        namespace = self._database.deployment_namespace
        with self._database.connect() as connection:
            return acquire_lease_in_transaction(
                connection, namespace, session_id, owner_instance_id=owner,
                ttl=validated_ttl, checkpoint=requested, maximum_ttl=self._maximum_ttl,
            )

    def heartbeat(
        self, session_id: SessionId, *, fence: LeaseFence, ttl: timedelta, checkpoint: int,
    ) -> WorkerLease:
        validated_ttl = self._ttl(ttl)
        next_checkpoint = self._checkpoint(checkpoint)
        namespace = self._database.deployment_namespace
        with self._database.connect() as connection:
            epoch = _lock_epoch(connection, namespace)
            previous, now = _lock_lease_and_clock(connection, namespace, session_id, update=True)
            if not _current(previous, epoch, fence, now):
                raise LeaseLostError("lease heartbeat rejected by the current fence")
            assert previous is not None
            if next_checkpoint < previous["checkpoint"]:
                raise LeaseCheckpointRegressionError("lease checkpoint must not move backwards")
            row = connection.execute(
                """UPDATE worker_leases SET checkpoint = %s, heartbeat_at = %s, expires_at = %s
                   WHERE deployment_namespace = %s AND session_id = %s RETURNING *""",
                (next_checkpoint, now, now + validated_ttl, namespace, session_id),
            ).fetchone()
            assert row is not None
        return _lease_from_row(row)

    def release(self, session_id: SessionId, *, fence: LeaseFence) -> None:
        namespace = self._database.deployment_namespace
        with self._database.connect() as connection:
            epoch = _lock_epoch(connection, namespace)
            previous, now = _lock_lease_and_clock(connection, namespace, session_id, update=True)
            if not _current(previous, epoch, fence, now):
                raise LeaseLostError("lease release rejected by the current fence")
            connection.execute(
                """UPDATE worker_leases SET released_at = %s
                   WHERE deployment_namespace = %s AND session_id = %s""",
                (now, namespace, session_id),
            )

    def get(self, session_id: SessionId) -> WorkerLease | None:
        with self._database.connect() as connection:
            row = connection.execute(
                """SELECT lease.* FROM worker_leases AS lease
                JOIN control_plane_epochs AS authority USING (deployment_namespace)
                WHERE lease.deployment_namespace = %s AND lease.session_id = %s
                  AND lease.control_plane_epoch = authority.epoch
                  AND lease.released_at IS NULL AND lease.expires_at > clock_timestamp()""",
                (self._database.deployment_namespace, session_id),
            ).fetchone()
        return None if row is None else _lease_from_row(row)

    def _ttl(self, ttl: timedelta) -> timedelta:
        return _validate_ttl(ttl, self._maximum_ttl)

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


def _validate_ttl(ttl: timedelta, maximum_ttl: timedelta) -> timedelta:
    if maximum_ttl <= timedelta(0):
        raise ValueError("maximum lease ttl must be positive")
    if ttl <= timedelta(0):
        raise ValueError("lease ttl must be positive")
    if ttl > maximum_ttl:
        raise ValueError("lease ttl exceeds configured maximum")
    return ttl


def acquire_lease_in_transaction(
    connection: Any, deployment_namespace: str, session_id: SessionId, *,
    owner_instance_id: str, ttl: timedelta, checkpoint: int | None = None,
    maximum_ttl: timedelta = DEFAULT_MAX_LEASE_TTL,
) -> WorkerLease:
    """Acquire the existing Session lease without committing the caller transaction."""
    validated_ttl = _validate_ttl(ttl, maximum_ttl)
    owner = PostgresLeaseStore._owner_instance_id(owner_instance_id)
    requested = None if checkpoint is None else PostgresLeaseStore._checkpoint(checkpoint)
    lock_session_lease_boundary(connection, deployment_namespace, session_id)
    epoch = _lock_epoch(connection, deployment_namespace)
    if epoch is None:
        raise PostgresControlPlaneEpochError("control-plane epoch is not bootstrapped")
    previous, now = _lock_lease_and_clock(
        connection, deployment_namespace, session_id, update=True
    )
    if previous is not None:
        if _active(previous, epoch, now):
            raise LeaseConflictError("session already has an active lease")
        if requested is not None and requested < previous["checkpoint"]:
            raise LeaseCheckpointRegressionError("lease checkpoint must not move backwards")
    next_checkpoint = requested if requested is not None else (
        0 if previous is None else previous["checkpoint"]
    )
    # The existing session advisory lock also serializes the absent-row case.
    row = connection.execute(
        """INSERT INTO worker_leases (
            deployment_namespace, session_id, control_plane_epoch,
            fencing_token, owner_instance_id, checkpoint,
            acquired_at, heartbeat_at, expires_at, released_at
        ) VALUES (%s, %s, %s, 1, %s, %s, %s, %s, %s, NULL)
        ON CONFLICT (deployment_namespace, session_id) DO UPDATE SET
            control_plane_epoch = EXCLUDED.control_plane_epoch,
            fencing_token = worker_leases.fencing_token + 1,
            owner_instance_id = EXCLUDED.owner_instance_id,
            checkpoint = EXCLUDED.checkpoint,
            acquired_at = EXCLUDED.acquired_at,
            heartbeat_at = EXCLUDED.heartbeat_at,
            expires_at = EXCLUDED.expires_at,
            released_at = NULL
        RETURNING *""",
        (deployment_namespace, session_id, epoch, owner, next_checkpoint,
         now, now, now + validated_ttl),
    ).fetchone()
    assert row is not None
    return _lease_from_row(row)


def _lock_epoch(connection: Any, namespace: str) -> UUID | None:
    row = connection.execute(
        """SELECT epoch FROM control_plane_epochs
           WHERE deployment_namespace = %s FOR SHARE""", (namespace,),
    ).fetchone()
    return None if row is None else UUID(str(row["epoch"]))


def _lock_lease_and_clock(
    connection: Any, namespace: str, session_id: SessionId, *, update: bool
) -> tuple[dict[str, Any] | None, datetime]:
    row = connection.execute(
        sql.SQL("""SELECT * FROM worker_leases
                   WHERE deployment_namespace = %s AND session_id = %s FOR {}""").format(
            sql.SQL("UPDATE" if update else "SHARE")
        ), (namespace, session_id),
    ).fetchone()
    # A WHERE clock_timestamp() predicate can be evaluated BEFORE waiting for
    # the row lock. This separate statement samples time only AFTER acquiring it.
    now: datetime = connection.execute("SELECT clock_timestamp() AS now").fetchone()["now"]
    return row, now.astimezone(UTC)


def _active(row: dict[str, Any], epoch: UUID | None, now: datetime) -> bool:
    return bool(
        row["control_plane_epoch"] == epoch
        and row["released_at"] is None and row["expires_at"] > now
    )


def _current(
    row: dict[str, Any] | None, epoch: UUID | None, fence: LeaseFence, now: datetime
) -> bool:
    return (
        row is not None and epoch == fence.control_plane_epoch and _active(row, epoch, now)
        and row["fencing_token"] == fence.fencing_token
        and row["owner_instance_id"] == fence.owner_instance_id
    )


def _lease_from_row(row: dict[str, Any]) -> WorkerLease:
    return WorkerLease(
        session_id=SessionId(row["session_id"]),
        fence=LeaseFence(
            control_plane_epoch=UUID(str(row["control_plane_epoch"])),
            fencing_token=row["fencing_token"],
            owner_instance_id=row["owner_instance_id"],
        ),
        checkpoint=row["checkpoint"], acquired_at=row["acquired_at"].astimezone(UTC),
        heartbeat_at=row["heartbeat_at"].astimezone(UTC),
        expires_at=row["expires_at"].astimezone(UTC),
    )


def assert_current_lease_fence(
    connection: Any, deployment_namespace: str, session_id: SessionId, fence: LeaseFence,
) -> None:
    """Hold epoch SHARE then lease SHARE and validate at the post-lock DB time.

    This is a point-in-time check, not a guarantee across later business-row waits.
    """
    epoch = _lock_epoch(connection, deployment_namespace)
    if epoch is None or epoch != fence.control_plane_epoch:
        raise LeaseLostError("mutation rejected by the current lease fence")
    row, now = _lock_lease_and_clock(connection, deployment_namespace, session_id, update=False)
    if not _current(row, epoch, fence, now):
        raise LeaseLostError("mutation rejected by the current lease fence")


def lock_session_lease_boundary(
    connection: Any, deployment_namespace: str, session_id: SessionId,
) -> None:
    """Serialize Lease acquisition with terminal aggregate transitions."""
    connection.execute(
        "SELECT pg_advisory_xact_lock(hashtextextended(%s, 0))",
        (f"{deployment_namespace}:{session_id}",),
    )
