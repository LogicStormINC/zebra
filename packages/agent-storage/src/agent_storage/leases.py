from datetime import datetime
from pathlib import Path
from uuid import UUID

from agent_core.domain.identifiers import SessionId
from agent_core.domain.leases import WorkerLease
from agent_core.ports.lease_store import LeaseStorePort

from agent_storage.database import SQLiteDatabase


class LeaseConflictError(ValueError):
    """Raised when a worker cannot acquire or update an active lease."""


class SQLiteLeaseStore(LeaseStorePort):
    def __init__(self, database_path: str | Path) -> None:
        self._database = SQLiteDatabase(database_path)
        self._initialize()

    def acquire(
        self,
        session_id: SessionId,
        *,
        worker_id: str,
        acquired_at: datetime,
        expires_at: datetime,
        checkpoint: int = 0,
    ) -> WorkerLease:
        with self._database.connect() as connection:
            existing = self.get(session_id)
            if existing is not None and existing.expires_at > acquired_at:
                if existing.worker_id != worker_id:
                    raise LeaseConflictError("session already leased by another worker")
                lease = self._build_lease(
                    session_id=session_id,
                    worker_id=worker_id,
                    checkpoint=checkpoint,
                    acquired_at=existing.acquired_at,
                    heartbeat_at=acquired_at,
                    expires_at=expires_at,
                )
            else:
                lease = self._build_lease(
                    session_id=session_id,
                    worker_id=worker_id,
                    checkpoint=checkpoint,
                    acquired_at=acquired_at,
                    heartbeat_at=acquired_at,
                    expires_at=expires_at,
                )
            connection.execute(
                """
                INSERT INTO worker_leases (
                    session_id,
                    worker_id,
                    checkpoint,
                    acquired_at,
                    heartbeat_at,
                    expires_at
                ) VALUES (?, ?, ?, ?, ?, ?)
                ON CONFLICT(session_id) DO UPDATE SET
                    worker_id = excluded.worker_id,
                    checkpoint = excluded.checkpoint,
                    acquired_at = excluded.acquired_at,
                    heartbeat_at = excluded.heartbeat_at,
                    expires_at = excluded.expires_at
                """,
                (
                    str(lease.session_id),
                    lease.worker_id,
                    lease.checkpoint,
                    lease.acquired_at.isoformat(),
                    lease.heartbeat_at.isoformat(),
                    lease.expires_at.isoformat(),
                ),
            )
        return lease

    def heartbeat(
        self,
        session_id: SessionId,
        *,
        worker_id: str,
        heartbeat_at: datetime,
        expires_at: datetime,
        checkpoint: int,
    ) -> WorkerLease:
        existing = self.get(session_id)
        if existing is None or existing.expires_at <= heartbeat_at:
            raise LeaseConflictError("cannot heartbeat an expired or missing lease")
        if existing.worker_id != worker_id:
            raise LeaseConflictError("cannot heartbeat another worker's lease")

        lease = self._build_lease(
            session_id=session_id,
            worker_id=worker_id,
            checkpoint=checkpoint,
            acquired_at=existing.acquired_at,
            heartbeat_at=heartbeat_at,
            expires_at=expires_at,
        )
        with self._database.connect() as connection:
            connection.execute(
                """
                UPDATE worker_leases
                SET checkpoint = ?, heartbeat_at = ?, expires_at = ?
                WHERE session_id = ? AND worker_id = ?
                """,
                (
                    lease.checkpoint,
                    lease.heartbeat_at.isoformat(),
                    lease.expires_at.isoformat(),
                    str(session_id),
                    worker_id,
                ),
            )
        return lease

    def release(self, session_id: SessionId, *, worker_id: str) -> None:
        with self._database.connect() as connection:
            connection.execute(
                """
                DELETE FROM worker_leases
                WHERE session_id = ? AND worker_id = ?
                """,
                (str(session_id), worker_id),
            )

    def get(self, session_id: SessionId) -> WorkerLease | None:
        with self._database.connect() as connection:
            row = connection.execute(
                """
                SELECT
                    session_id,
                    worker_id,
                    checkpoint,
                    acquired_at,
                    heartbeat_at,
                    expires_at
                FROM worker_leases
                WHERE session_id = ?
                """,
                (str(session_id),),
            ).fetchone()
        if row is None:
            return None
        return self._build_lease(
            session_id=SessionId(UUID(row["session_id"])),
            worker_id=row["worker_id"],
            checkpoint=row["checkpoint"],
            acquired_at=datetime.fromisoformat(row["acquired_at"]),
            heartbeat_at=datetime.fromisoformat(row["heartbeat_at"]),
            expires_at=datetime.fromisoformat(row["expires_at"]),
        )

    def _initialize(self) -> None:
        with self._database.connect() as connection:
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

    @staticmethod
    def _build_lease(
        *,
        session_id: SessionId,
        worker_id: str,
        checkpoint: int,
        acquired_at: datetime,
        heartbeat_at: datetime,
        expires_at: datetime,
    ) -> WorkerLease:
        return WorkerLease(
            session_id=session_id,
            worker_id=worker_id,
            checkpoint=checkpoint,
            acquired_at=acquired_at,
            heartbeat_at=heartbeat_at,
            expires_at=expires_at,
        )
