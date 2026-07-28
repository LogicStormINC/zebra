import sqlite3
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import UUID, uuid4

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

from agent_storage.database import SQLiteDatabase, ensure_column

_LOCAL_NAMESPACE = "local"


class SQLiteLeaseStore(LeaseStorePort):
    def __init__(
        self,
        database_path: str | Path,
        *,
        clock: Callable[[], datetime] | None = None,
        maximum_ttl: timedelta = DEFAULT_MAX_LEASE_TTL,
    ) -> None:
        self._database = SQLiteDatabase(database_path)
        self._clock = clock or (lambda: datetime.now(UTC))
        if maximum_ttl <= timedelta(0):
            raise ValueError("maximum lease ttl must be positive")
        self._maximum_ttl = maximum_ttl
        self._initialize()

    def acquire(
        self,
        session_id: SessionId,
        *,
        owner_instance_id: str,
        ttl: timedelta,
        checkpoint: int | None = None,
    ) -> WorkerLease:
        now, expires_at = self._lease_window(ttl)
        owner = self._owner_instance_id(owner_instance_id)
        requested_checkpoint = 0 if checkpoint is None else self._checkpoint(checkpoint)
        preserve_checkpoint = checkpoint is None
        with self._database.connect() as connection:
            epoch = self._current_epoch(connection)
            row = connection.execute(
                """
                INSERT INTO worker_leases (
                    session_id, worker_id, checkpoint, acquired_at, heartbeat_at,
                    expires_at, control_plane_epoch, fencing_token, released_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, 1, NULL)
                ON CONFLICT(session_id) DO UPDATE SET
                    worker_id = excluded.worker_id,
                    checkpoint = CASE
                        WHEN ? THEN worker_leases.checkpoint
                        ELSE excluded.checkpoint
                    END,
                    acquired_at = excluded.acquired_at,
                    heartbeat_at = excluded.heartbeat_at,
                    expires_at = excluded.expires_at,
                    control_plane_epoch = excluded.control_plane_epoch,
                    fencing_token = worker_leases.fencing_token + 1,
                    released_at = NULL
                WHERE (
                    worker_leases.control_plane_epoch != excluded.control_plane_epoch
                    OR worker_leases.released_at IS NOT NULL
                    OR julianday(worker_leases.expires_at) <= julianday(excluded.acquired_at)
                )
                AND (? OR excluded.checkpoint >= worker_leases.checkpoint)
                RETURNING *
                """,
                (
                    str(session_id),
                    owner,
                    requested_checkpoint,
                    now.isoformat(),
                    now.isoformat(),
                    expires_at.isoformat(),
                    str(epoch),
                    preserve_checkpoint,
                    preserve_checkpoint,
                ),
            ).fetchone()
            if row is None:
                existing = connection.execute(
                    """
                    SELECT checkpoint,
                           control_plane_epoch = (
                               SELECT epoch FROM control_plane_epochs
                               WHERE deployment_namespace = 'local'
                           )
                           AND released_at IS NULL
                           AND julianday(expires_at) > julianday(?) AS is_active
                    FROM worker_leases WHERE session_id = ?
                    """,
                    (now.isoformat(), str(session_id)),
                ).fetchone()
                if existing is not None and existing["is_active"]:
                    raise LeaseConflictError("session already has an active lease")
                if (
                    checkpoint is not None
                    and existing is not None
                    and checkpoint < existing["checkpoint"]
                ):
                    raise LeaseCheckpointRegressionError("lease checkpoint must not move backwards")
                raise LeaseConflictError("session already has an active lease")
        return self._lease_from_row(row)

    def heartbeat(
        self,
        session_id: SessionId,
        *,
        fence: LeaseFence,
        ttl: timedelta,
        checkpoint: int,
    ) -> WorkerLease:
        now, expires_at = self._lease_window(ttl)
        next_checkpoint = self._checkpoint(checkpoint)
        with self._database.connect() as connection:
            row = connection.execute(
                """
                UPDATE worker_leases
                SET checkpoint = ?, heartbeat_at = ?, expires_at = ?
                WHERE session_id = ?
                  AND control_plane_epoch = ?
                  AND control_plane_epoch = (
                    SELECT epoch FROM control_plane_epochs
                    WHERE deployment_namespace = 'local'
                  )
                  AND fencing_token = ?
                  AND worker_id = ?
                  AND released_at IS NULL
                  AND julianday(expires_at) > julianday(?)
                  AND checkpoint <= ?
                RETURNING *
                """,
                (
                    next_checkpoint,
                    now.isoformat(),
                    expires_at.isoformat(),
                    str(session_id),
                    str(fence.control_plane_epoch),
                    fence.fencing_token,
                    fence.owner_instance_id,
                    now.isoformat(),
                    next_checkpoint,
                ),
            ).fetchone()
            if row is None:
                existing = connection.execute(
                    """
                    SELECT checkpoint FROM worker_leases
                    WHERE session_id = ?
                      AND control_plane_epoch = ?
                      AND control_plane_epoch = (
                        SELECT epoch FROM control_plane_epochs
                        WHERE deployment_namespace = 'local'
                      )
                      AND fencing_token = ?
                      AND worker_id = ?
                      AND released_at IS NULL
                      AND julianday(expires_at) > julianday(?)
                    """,
                    (
                        str(session_id),
                        str(fence.control_plane_epoch),
                        fence.fencing_token,
                        fence.owner_instance_id,
                        now.isoformat(),
                    ),
                ).fetchone()
                if existing is not None and next_checkpoint < existing["checkpoint"]:
                    raise LeaseCheckpointRegressionError("lease checkpoint must not move backwards")
                raise LeaseLostError("lease heartbeat rejected by the current fence")
        return self._lease_from_row(row)

    def release(self, session_id: SessionId, *, fence: LeaseFence) -> None:
        now = self._now()
        with self._database.connect() as connection:
            row = connection.execute(
                """
                UPDATE worker_leases
                SET released_at = ?
                WHERE session_id = ?
                  AND control_plane_epoch = ?
                  AND control_plane_epoch = (
                    SELECT epoch FROM control_plane_epochs
                    WHERE deployment_namespace = 'local'
                  )
                  AND fencing_token = ?
                  AND worker_id = ?
                  AND released_at IS NULL
                  AND julianday(expires_at) > julianday(?)
                RETURNING session_id
                """,
                (
                    now.isoformat(),
                    str(session_id),
                    str(fence.control_plane_epoch),
                    fence.fencing_token,
                    fence.owner_instance_id,
                    now.isoformat(),
                ),
            ).fetchone()
        if row is None:
            raise LeaseLostError("lease release rejected by the current fence")

    def get(self, session_id: SessionId) -> WorkerLease | None:
        now = self._now()
        with self._database.connect() as connection:
            row = connection.execute(
                """
                SELECT * FROM worker_leases
                WHERE session_id = ?
                  AND control_plane_epoch = (
                    SELECT epoch FROM control_plane_epochs
                    WHERE deployment_namespace = 'local'
                  )
                  AND released_at IS NULL
                  AND julianday(expires_at) > julianday(?)
                """,
                (str(session_id), now.isoformat()),
            ).fetchone()
        return None if row is None else self._lease_from_row(row)

    @classmethod
    def _lease_from_row(cls, row: sqlite3.Row) -> WorkerLease:
        return WorkerLease(
            session_id=SessionId(UUID(row["session_id"])),
            fence=LeaseFence(
                control_plane_epoch=UUID(row["control_plane_epoch"]),
                fencing_token=row["fencing_token"],
                owner_instance_id=row["worker_id"],
            ),
            checkpoint=row["checkpoint"],
            acquired_at=datetime.fromisoformat(row["acquired_at"]),
            heartbeat_at=datetime.fromisoformat(row["heartbeat_at"]),
            expires_at=datetime.fromisoformat(row["expires_at"]),
        )

    def _initialize(self) -> None:
        with self._database.connect() as connection:
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS control_plane_epochs (
                    deployment_namespace TEXT PRIMARY KEY,
                    epoch TEXT NOT NULL
                )
                """
            )
            connection.execute(
                """
                INSERT OR IGNORE INTO control_plane_epochs VALUES (?, ?)
                """,
                (_LOCAL_NAMESPACE, str(uuid4())),
            )
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS worker_leases (
                    session_id TEXT PRIMARY KEY,
                    worker_id TEXT NOT NULL,
                    checkpoint INTEGER NOT NULL,
                    acquired_at TEXT NOT NULL,
                    heartbeat_at TEXT NOT NULL,
                    expires_at TEXT NOT NULL
                )
                """
            )
            ensure_column(connection, "worker_leases", "control_plane_epoch", "TEXT")
            ensure_column(
                connection,
                "worker_leases",
                "fencing_token",
                "INTEGER NOT NULL DEFAULT 0",
            )
            ensure_column(connection, "worker_leases", "released_at", "TEXT")
            epoch = self._current_epoch(connection)
            # ponytail: incomplete pre-fence rows fail closed on every initialization;
            # token >= 1 rows are already migrated and remain untouched.
            connection.execute(
                """
                UPDATE worker_leases
                SET control_plane_epoch = COALESCE(control_plane_epoch, ?),
                    fencing_token = 0,
                    released_at = COALESCE(released_at, expires_at)
                WHERE control_plane_epoch IS NULL OR fencing_token < 1
                """,
                (str(epoch),),
            )

    @staticmethod
    def _current_epoch(connection: sqlite3.Connection) -> UUID:
        row = connection.execute(
            "SELECT epoch FROM control_plane_epochs WHERE deployment_namespace = ?",
            (_LOCAL_NAMESPACE,),
        ).fetchone()
        if row is None:
            raise RuntimeError("local control-plane epoch is missing")
        return UUID(row["epoch"])

    def _lease_window(self, ttl: timedelta) -> tuple[datetime, datetime]:
        if ttl <= timedelta(0):
            raise ValueError("lease ttl must be positive")
        if ttl > self._maximum_ttl:
            raise ValueError("lease ttl exceeds configured maximum")
        now = self._now()
        return now, now + ttl

    def _now(self) -> datetime:
        now = self._clock()
        if now.tzinfo is None:
            raise ValueError("lease clock must return a timezone-aware timestamp")
        return now

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
