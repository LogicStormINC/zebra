"""Control-lease port: one active controller per client run binding."""

from datetime import timedelta
from typing import Protocol
from uuid import UUID

from agent_core.domain.client_sessions import (
    ClientControlFence,
    ClientControlLease,
)
from agent_core.domain.identifiers import ClientSessionId


class ClientControlLeasePort(Protocol):
    def claim_controller(
        self,
        run_binding_id: UUID,
        *,
        client_session_id: ClientSessionId,
        fence: ClientControlFence,
        ttl: timedelta,
    ) -> ClientControlLease:
        """CAS claim; only one of two racing tabs succeeds."""

    def renew(
        self,
        run_binding_id: UUID,
        *,
        fence: ClientControlFence,
        ttl: timedelta,
    ) -> ClientControlLease:
        """Renewal requires the current fence; stale fences write zero rows."""

    def release(self, run_binding_id: UUID, *, fence: ClientControlFence) -> None: ...

    def get_active(self, run_binding_id: UUID) -> ClientControlLease | None: ...
