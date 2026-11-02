"""Public identities stay stable; narrow readers avoid full application bootstrap."""

# ruff: noqa: F405 -- TYPE_CHECKING exports define public types.
from importlib import import_module as _import_module
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from ._public_exports import *  # noqa: F403
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
_EXPORTS = {
    "ClaimedSession": ("zebra_agent_worker.claims", "ClaimedSession"),
    "SessionClaimService": ("zebra_agent_worker.claims", "SessionClaimService"),
    "CommandConsumption": ("zebra_agent_worker.command_consumer", "CommandConsumption"),
    "SessionCommandConsumer": ("zebra_agent_worker.command_consumer", "SessionCommandConsumer"),
    "CancelledSession": ("zebra_agent_worker.control", "CancelledSession"),
    "SessionControlError": ("zebra_agent_worker.control", "SessionControlError"),
    "SessionControlService": ("zebra_agent_worker.control", "SessionControlService"),
    "SuspendedSession": ("zebra_agent_worker.control", "SuspendedSession"),
    "SessionExecutionService": ("zebra_agent_worker.execution", "SessionExecutionService"),
    "ExecutedSession": ("zebra_agent_worker.execution_finalization", "ExecutedSession"),
    "WorkerExecutionError": ("zebra_agent_worker.execution_finalization", "WorkerExecutionError"),
    "WorkerLoopCycleResult": ("zebra_agent_worker.loop", "WorkerLoopCycleResult"),
    "WorkerLoopRunResult": ("zebra_agent_worker.loop", "WorkerLoopRunResult"),
    "WorkerLoopService": ("zebra_agent_worker.loop", "WorkerLoopService"),
    "build_worker_loop_service": ("zebra_agent_worker.loop", "build_worker_loop_service"),
    "worker_banner": ("zebra_agent_worker.main", "worker_banner"),
    "ModelCallIndexer": ("zebra_agent_worker.model_call_index", "ModelCallIndexer"),
    "RecoveredSession": ("zebra_agent_worker.recovery", "RecoveredSession"),
    "SessionRecoveryError": ("zebra_agent_worker.recovery", "SessionRecoveryError"),
    "SessionRecoveryService": ("zebra_agent_worker.recovery", "SessionRecoveryService"),
    "ResumedSession": ("zebra_agent_worker.resume", "ResumedSession"),
    "SessionResumeError": ("zebra_agent_worker.resume", "SessionResumeError"),
    "SessionResumeService": ("zebra_agent_worker.resume", "SessionResumeService"),
    "ToolRunIndexer": ("zebra_agent_worker.tool_run_index", "ToolRunIndexer"),
}


def __getattr__(name: str) -> object:
    if name not in _EXPORTS:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
    module, symbol = _EXPORTS[name]
    value = getattr(_import_module(module, __name__), symbol)
    globals()[name] = value
    return value


def __dir__() -> list[str]:
    return sorted(set(globals()) | set(__all__))
