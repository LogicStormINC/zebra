"""Control-lease port: one active controller per client run."""

from datetime import timedelta
from typing import Protocol
from uuid import UUID

from agent_core.domain.client_sessions import (
    ClientControlFence,
    ClientControlLease,
)
from agent_core.domain.identifiers import ClientSessionId, TaskId


class ClientControlLeasePort(Protocol):
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
        """CAS claim on (task, run); only one of two racing tabs succeeds."""

    def renew(
        self,
        run_binding_id: UUID,
        *,
        task_id: TaskId,
        run_id: str,
        fence: ClientControlFence,
        ttl: timedelta,
    ) -> ClientControlLease:
        """Renewal requires the current fence; stale fences write zero rows."""

    def release(
        self,
        run_binding_id: UUID,
        *,
        task_id: TaskId,
        run_id: str,
        fence: ClientControlFence,
    ) -> None: ...

    def get_active(self, run_binding_id: UUID) -> ClientControlLease | None: ...
