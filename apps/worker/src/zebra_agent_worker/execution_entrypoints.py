from datetime import datetime

from agent_core.domain.identifiers import SessionId
from agent_core.domain.leases import WorkerLease

import zebra_agent_worker.execution_finalization as execution_finalization
from zebra_agent_worker.execution_recovery import (
    execute_existing_lease,
    execute_session_with_lease,
)


class SessionExecutionEntrypoints:
    def execute_session(
        self,
        session_id: SessionId,
        *,
        worker_id: str,
        executed_at: datetime | None = None,
        lease_ttl_seconds: int = 30,
    ) -> execution_finalization.ExecutedSession:
        return execute_session_with_lease(
            self,
            session_id,
            worker_id=worker_id,
            executed_at=executed_at,
            lease_ttl_seconds=lease_ttl_seconds,
        )

    def execute_claimed_session(
        self,
        lease: WorkerLease,
        *,
        executed_at: datetime | None = None,
        lease_ttl_seconds: int = 30,
    ) -> execution_finalization.ExecutedSession:
        return execute_existing_lease(
            self, lease, executed_at=executed_at, lease_ttl_seconds=lease_ttl_seconds
        )
