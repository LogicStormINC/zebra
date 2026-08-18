"""Local-profile inline execution adapter (AL-API-BOUNDARY-01).

The cloud API surface must not depend on Worker or Runtime execution. This
module is the one local composition seam that may import them, and it is
imported lazily only when the local profile actually executes inline. The
cloud command path never touches this module.
"""

from __future__ import annotations

from agent_runtime import run_local_harness
from agent_storage import LeaseConflictError
from zebra_agent_worker import (
    SessionClaimService,
    SessionControlError,
    SessionControlService,
    SessionExecutionService,
    SessionRecoveryError,
    SessionRecoveryService,
    SessionResumeError,
    SessionResumeService,
    WorkerExecutionError,
)

__all__ = [
    "LeaseConflictError",
    "SessionControlError",
    "SessionControlService",
    "SessionClaimService",
    "SessionExecutionService",
    "SessionRecoveryError",
    "SessionRecoveryService",
    "SessionResumeError",
    "SessionResumeService",
    "WorkerExecutionError",
    "run_local_harness",
]
