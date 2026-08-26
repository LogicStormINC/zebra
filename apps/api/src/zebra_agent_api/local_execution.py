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

from zebra_agent_api.responses import ApiResponse, conflict, service_unavailable

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


def map_execution_error(session_id: str, exc: BaseException) -> ApiResponse | None:
    """Map a Worker execution error to an API response, or None to raise."""

    from agent_core.domain.leases import LeaseConflictError  # noqa: PLC0415
    from zebra_agent_worker.execution_finalization import (  # noqa: PLC0415
        WorkerExecutionError,
    )
    from zebra_agent_worker.recovery import SessionRecoveryError  # noqa: PLC0415
    from zebra_agent_worker.resume import SessionResumeError  # noqa: PLC0415

    if isinstance(exc, SessionRecoveryError):
        return ApiResponse(
            status_code=404,
            body={"session_id": session_id, "status": "not_found"},
        )
    if isinstance(exc, SessionResumeError):
        return conflict(
            session_id=session_id,
            status="not_resumable",
            reason=(
                "awaiting_next_turn_message"
                if "awaiting the next turn" in str(exc)
                else "cannot_resume_terminal_session"
            ),
        )
    if isinstance(exc, LeaseConflictError):
        return conflict(
            session_id=session_id,
            status="lease_conflict",
            reason="session_already_leased",
        )
    if isinstance(exc, WorkerExecutionError):
        return conflict(
            session_id=session_id,
            status="execution_error",
            reason=str(exc),
        )
    if isinstance(exc, ValueError):
        return service_unavailable(
            status="model_gateway_unavailable",
            reason=str(exc),
        )
    return None
