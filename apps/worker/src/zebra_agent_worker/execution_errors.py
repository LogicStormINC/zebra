"""Error classification helpers for session execution.

Split from ``execution.py`` to keep the main service file under the repository
size limit (AGENTS.md hard limit: 500 lines for source files).
"""

from __future__ import annotations

from agent_core.domain.context_capsule import ContextCapsuleValidationError
from agent_core.harness.models import HarnessAttemptOutcome, HarnessAttemptResult


def exception_attempt_result(
    exc: Exception, metadata: dict[str, object]
) -> HarnessAttemptResult:
    """Classify an unhandled exception into a terminal or recoverable result.

    CTX-ART-01: a capsule validation error that escapes the persistence
    fallback is a recovery signal, not a model execution failure. It must
    suspend (recoverable) rather than fail (terminal).
    """
    if isinstance(exc, ContextCapsuleValidationError):
        return HarnessAttemptResult(
            outcome=HarnessAttemptOutcome.SUSPENDED,
            summary=(
                "context capsule validation failed; execution can continue "
                "with a fresh context"
            ),
            metadata={**metadata, "stop_reason": "context_recovery_required"},
        )
    return HarnessAttemptResult(
        outcome=HarnessAttemptOutcome.FAILED,
        summary="model execution failed",
        metadata=metadata,
    )


def error_metadata(
    exc: Exception,
    clarification: object | None,
    continuation: object | None,
) -> dict[str, object]:
    """Build error metadata from an unhandled exception and execution context."""
    raw_error = str(exc).strip()
    model_calls = (
        getattr(clarification, "model_calls_used", None)
        or getattr(continuation, "model_calls_used", None)
    )
    tool_calls = (
        getattr(clarification, "tool_calls_executed", None)
        or getattr(continuation, "tool_calls_executed", None)
    )
    error_type = type(exc).__name__
    return {
        "stop_reason": "model_execution_failed",
        "error_type": error_type,
        "model_calls_used": (model_calls or 0) + 1,
        "tool_calls_executed": tool_calls or 0,
        "error_message": raw_error or f"{error_type} (no detail was provided)",
    }
