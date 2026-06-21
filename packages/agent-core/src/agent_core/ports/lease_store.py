from datetime import datetime
from typing import Protocol

from agent_core.domain.identifiers import SessionId
from agent_core.domain.leases import WorkerLease


class LeaseStorePort(Protocol):
    def acquire(
        self,
        session_id: SessionId,
        *,
        worker_id: str,
        acquired_at: datetime,
        expires_at: datetime,
        checkpoint: int = 0,
    ) -> WorkerLease: ...

    def heartbeat(
        self,
        session_id: SessionId,
        *,
        worker_id: str,
        heartbeat_at: datetime,
        expires_at: datetime,
        checkpoint: int,
    ) -> WorkerLease: ...

    def release(self, session_id: SessionId, *, worker_id: str) -> None: ...

    def get(self, session_id: SessionId) -> WorkerLease | None: ...
