"""Public exports load on demand; direct submodule imports stay bounded."""

# ruff: noqa: F405 -- TYPE_CHECKING exports and __getattr__ define the public names.

from importlib import import_module as _import_module
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from ._public_exports import *  # noqa: F403

__all__ = [
    "FirstToolCallSelectionStrategy",
    "HarnessAttempt",
    "HarnessAttemptOutcome",
    "HarnessAttemptResult",
    "HarnessAttemptTrace",
    "HarnessContext",
    "HarnessEventDraft",
    "HarnessEventRecorder",
    "HarnessLoop",
    "HarnessModelStep",
    "HarnessLoopResult",
    "NoopPlanner",
    "NoopVerifier",
    "PlannerHook",
    "PlannerResult",
    "RetryPlanHint",
    "HarnessRunResult",
    "HarnessRunTrace",
    "HarnessStopReason",
    "HarnessStoppingPolicy",
    "SingleAttemptOrchestrator",
    "StepClock",
    "SystemClock",
    "HarnessTask",
    "HarnessToolTrace",
    "HarnessTraceProjector",
    "ModelCallMetadata",
    "ModelCallRecord",
    "ToolCallSelection",
    "ToolCallSelectionStrategy",
    "ToolRunRecord",
    "VerifierHook",
    "VerifierResult",
    "build_retry_plan_hint",
    "ModelCompletion",
    "ModelTokenBreakdown",
    "ModelToolDefinition",
    "ModelToolOrigin",
    "ModelUsage",
    "ScriptedModelGateway",
    "ScriptedModelResponse",
    "LeaseCheckpointRegressionError",
    "LeaseConflictError",
    "DEFAULT_MAX_LEASE_TTL",
    "LeaseFence",
    "LeaseLostError",
    "WorkerLease",
]


def __getattr__(name: str) -> object:
    if name not in __all__:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
    # ponytail: first public access loads the original aggregate; per-name lazy
    # exports are only needed if aggregate consumers also need lower startup cost.
    value = getattr(_import_module(f"{__name__}._public_exports"), name)
    globals()[name] = value
    return value


def __dir__() -> list[str]:
    return sorted(set(globals()) | set(__all__))
