"""Worker app package for Zebra Agent (lazy re-exports via PEP 562).

CA-HA-03 D1-v2: the eager root pulled control/loop/main/recovery chains
(~1.5s in session children that only need the execution path). Re-exports
resolve on first attribute access.
"""

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    # Static-analysis view only; never executed at runtime.
    from zebra_agent_worker.claims import ClaimedSession, SessionClaimService
    from zebra_agent_worker.command_consumer import (
        CommandConsumption,
        SessionCommandConsumer,
    )
    from zebra_agent_worker.control import (
        CancelledSession,
        SessionControlError,
        SessionControlService,
        SuspendedSession,
    )
    from zebra_agent_worker.execution import SessionExecutionService
    from zebra_agent_worker.execution_finalization import (
        ExecutedSession,
        WorkerExecutionError,
    )
    from zebra_agent_worker.loop import (
        WorkerLoopCycleResult,
        WorkerLoopRunResult,
        WorkerLoopService,
        build_worker_loop_service,
    )
    from zebra_agent_worker.main import worker_banner
    from zebra_agent_worker.model_call_index import ModelCallIndexer
    from zebra_agent_worker.recovery import (
        RecoveredSession,
        SessionRecoveryError,
        SessionRecoveryService,
    )
    from zebra_agent_worker.resume import (
        ResumedSession,
        SessionResumeError,
        SessionResumeService,
    )
    from zebra_agent_worker.tool_run_index import ToolRunIndexer

_LAZY_EXPORTS: dict[str, str] = {
    "build_worker_loop_service": "zebra_agent_worker.loop",
    "ClaimedSession": "zebra_agent_worker.claims",
    "CommandConsumption": "zebra_agent_worker.command_consumer",
    "CancelledSession": "zebra_agent_worker.control",
    "ExecutedSession": "zebra_agent_worker.execution_finalization",
    "ModelCallIndexer": "zebra_agent_worker.model_call_index",
    "RecoveredSession": "zebra_agent_worker.recovery",
    "ResumedSession": "zebra_agent_worker.resume",
    "SessionClaimService": "zebra_agent_worker.claims",
    "SessionCommandConsumer": "zebra_agent_worker.command_consumer",
    "SessionControlError": "zebra_agent_worker.control",
    "SessionControlService": "zebra_agent_worker.control",
    "SessionExecutionService": "zebra_agent_worker.execution",
    "SessionRecoveryError": "zebra_agent_worker.recovery",
    "SessionRecoveryService": "zebra_agent_worker.recovery",
    "SessionResumeError": "zebra_agent_worker.resume",
    "SessionResumeService": "zebra_agent_worker.resume",
    "SuspendedSession": "zebra_agent_worker.control",
    "ToolRunIndexer": "zebra_agent_worker.tool_run_index",
    "WorkerExecutionError": "zebra_agent_worker.execution_finalization",
    "WorkerLoopCycleResult": "zebra_agent_worker.loop",
    "WorkerLoopRunResult": "zebra_agent_worker.loop",
    "WorkerLoopService": "zebra_agent_worker.loop",
    "worker_banner": "zebra_agent_worker.main",
}

__all__ = [
    "ClaimedSession",
    "CommandConsumption",
    "CancelledSession",
    "ExecutedSession",
    "ModelCallIndexer",
    "RecoveredSession",
    "SessionClaimService",
    "SessionCommandConsumer",
    "SessionControlError",
    "SessionControlService",
    "SessionExecutionService",
    "WorkerLoopCycleResult",
    "WorkerLoopRunResult",
    "WorkerLoopService",
    "SessionRecoveryError",
    "SessionRecoveryService",
    "ResumedSession",
    "SessionResumeError",
    "SessionResumeService",
    "SuspendedSession",
    "ToolRunIndexer",
    "WorkerExecutionError",
    "build_worker_loop_service",
    "worker_banner",
]


def __getattr__(name: str) -> object:
    """Resolve a re-exported attribute on first access (PEP 562)."""
    module_path = _LAZY_EXPORTS.get(name)
    if module_path is None:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
    from importlib import import_module

    value = getattr(import_module(module_path), name)
    globals()[name] = value  # Cache: subsequent lookups bypass this hook.
    return value


def __dir__() -> list[str]:
    return sorted(set(globals()) | set(_LAZY_EXPORTS))
