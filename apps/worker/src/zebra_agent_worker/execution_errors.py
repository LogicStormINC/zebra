"""Error classification helpers for session execution.

Split from ``execution.py`` to keep the main service file under the repository
size limit (AGENTS.md hard limit: 500 lines for source files).
"""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager

from agent_core.domain.context_capsule import ContextCapsuleValidationError
from agent_core.harness.context_window import ContextWindowExceededError
from agent_core.harness.models import HarnessAttemptOutcome, HarnessAttemptResult
from agent_core.ports.model_gateway import ModelResponseRejectedError
from agent_integrations.model_errors import ModelProviderError


def exception_attempt_result(exc: Exception, metadata: dict[str, object]) -> HarnessAttemptResult:
    """Classify an unhandled exception into a terminal or recoverable result.

    CTX-ART-01: a capsule validation error that escapes the persistence
    fallback is a recovery signal, not a model execution failure. It must
    suspend (recoverable) rather than fail (terminal).
    """
    if isinstance(exc, ContextCapsuleValidationError):
        return HarnessAttemptResult(
            outcome=HarnessAttemptOutcome.SUSPENDED,
            summary=(
                "context capsule validation failed; execution can continue with a fresh context"
            ),
            metadata={**metadata, "stop_reason": "context_recovery_required"},
        )
    if isinstance(exc, ContextWindowExceededError):
        return HarnessAttemptResult(
            outcome=HarnessAttemptOutcome.SUSPENDED,
            summary="context window remains over budget after strict compaction",
            metadata={**metadata, "stop_reason": "context_window_exceeded"},
        )
    if isinstance(exc, ModelResponseRejectedError):
        return HarnessAttemptResult(
            outcome=HarnessAttemptOutcome.SUSPENDED,
            summary="model response repair exhausted; execution can be resumed safely",
            metadata={**metadata, "stop_reason": "model_response_repair_exhausted"},
        )
    if isinstance(exc, ModelProviderError) and exc.retryable:
        return HarnessAttemptResult(
            outcome=HarnessAttemptOutcome.SUSPENDED,
            summary="model provider retry budget exhausted; execution can be resumed safely",
            metadata={**metadata, "stop_reason": "model_provider_retry_exhausted"},
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
    model_calls = getattr(clarification, "model_calls_used", None) or getattr(
        continuation, "model_calls_used", None
    )
    tool_calls = getattr(clarification, "tool_calls_executed", None) or getattr(
        continuation, "tool_calls_executed", None
    )
    error_type = type(exc).__name__
    response_repair_count = (
        exc.response_repair_count if isinstance(exc, ModelResponseRejectedError) else 0
    )
    metadata: dict[str, object] = {
        "stop_reason": "model_execution_failed",
        "error_type": error_type,
        "model_calls_used": (model_calls or 0) + 1 + response_repair_count,
        "tool_calls_executed": tool_calls or 0,
        "error_message": raw_error or f"{error_type} (no detail was provided)",
    }
    if isinstance(exc, ModelResponseRejectedError):
        metadata.update(exc.metadata())
    elif isinstance(exc, ContextWindowExceededError):
        metadata.update(
            {
                "estimated_input_tokens": exc.plan.estimated_input_tokens,
                "input_token_limit": exc.plan.input_token_limit,
                "context_profile": exc.plan.profile_name,
                "token_breakdown": exc.plan.token_breakdown,
                "attempted_strategies": list(exc.plan.attempted_strategies),
            }
        )
    elif isinstance(exc, ModelProviderError):
        metadata.update(
            {
                "normalized_error": exc.normalized_error,
                "retryable": exc.retryable,
                "retry_count": exc.retry_count,
            }
        )
    return metadata


def is_sequence_race(exc: BaseException) -> bool:
    """True only for the typed LOST SEQUENCE CAS.

    Both storage adapters raise SessionEventSequenceConflictError when
    another event already took this (session, sequence) — the single
    retriable race. Event-id reuse, same-key/different-payload retries and
    every other integrity violation keep their own errors and fail
    closed; text matching is deliberately gone.
    """

    from agent_storage import SessionEventSequenceConflictError  # noqa: PLC0415

    return isinstance(exc, SessionEventSequenceConflictError)


@contextmanager
def sequence_race_guard(context: str) -> Iterator[None]:
    """A lost durable sequence race means the snapshot is stale.

    The caller re-recovers once instead of raising past the Worker
    boundary (ADR-026 §5).
    """
    from zebra_agent_worker.execution_preflight import (  # noqa: PLC0415
        StaleExecutionSnapshot,
    )

    try:
        yield
    except ValueError as exc:
        if is_sequence_race(exc):
            raise StaleExecutionSnapshot(context) from exc
        raise
