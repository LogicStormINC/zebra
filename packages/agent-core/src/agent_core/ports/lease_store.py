from datetime import timedelta
from typing import Protocol

from agent_core.domain.identifiers import SessionId
from agent_core.domain.leases import LeaseFence, WorkerLease


class LeaseStorePort(Protocol):
    def acquire(
        self,
        session_id: SessionId,
        *,
        owner_instance_id: str,
        ttl: timedelta,
        checkpoint: int | None = None,
    ) -> WorkerLease: ...

    def heartbeat(
        self,
        session_id: SessionId,
        *,
        fence: LeaseFence,
        ttl: timedelta,
        checkpoint: int,
    ) -> WorkerLease: ...

    def release(self, session_id: SessionId, *, fence: LeaseFence) -> None: ...

    def get(self, session_id: SessionId) -> WorkerLease | None: ...
