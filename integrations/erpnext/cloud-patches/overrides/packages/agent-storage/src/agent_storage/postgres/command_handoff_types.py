from dataclasses import dataclass
from enum import StrEnum
from uuid import UUID

from agent_core.domain.leases import WorkerLease


class HandoffStatus(StrEnum):
    PREPARING = "preparing"
    ACCEPTED = "accepted"
    DUPLICATE = "duplicate"
    RETIRED_NOOP = "retired_noop"
    BUSY = "busy"
    PRIOR_COMMAND_UNRECONCILED = "prior_command_unreconciled"
    REQUIRES_RECONCILIATION = "requires_reconciliation"
    UNSUPPORTED_FOR_EXECUTION_HANDOFF = "unsupported_for_execution_handoff"
    SCOPE_DEFERRED = "scope_deferred"
    SCOPE_SETTLED = "scope_settled"


@dataclass(frozen=True)
class CommandHandoff:
    status: HandoffStatus
    command_id: UUID
    accepted_event_id: UUID
    lease: WorkerLease | None = None


class _TerminalAfterLease(Exception):
    """Roll back the tentative acquisition without discarding reconciliation."""
