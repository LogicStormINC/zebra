"""Error classification helpers for session execution.

Split from ``execution.py`` to keep the main service file under the repository
size limit (AGENTS.md hard limit: 500 lines for source files).
"""

from __future__ import annotations

import logging
from collections.abc import Iterator
from contextlib import contextmanager

import psycopg
from agent_core.domain.context_capsule import ContextCapsuleValidationError
from agent_core.domain.coverage_contracts import CoverageRefusalReason
from agent_core.domain.execution_authority import ExecutionAuthorityResolutionError
from agent_core.domain.plugin_authority import PLUGIN_UNAVAILABLE, PluginAuthorityUnavailable
from agent_core.harness.context_window import ContextWindowExceededError
from agent_core.harness.models import HarnessAttemptOutcome, HarnessAttemptResult
from agent_core.harness.orchestration_events import continuation_metadata
from agent_core.harness.provider_continuation import ProviderContinuationUncertainError
from agent_core.ports.model_gateway import ModelResponseRejectedError
from agent_core.ports.runtime import RuntimeCapabilityError
from agent_core.ports.worker_progress import WorkerProgressTimeout
from agent_core.ports.workspace_projection_store import WorkerCommitConfirmationPending
from agent_integrations.model_errors import ModelProviderError

logger = logging.getLogger(__name__)


class WorkerExecutionError(ValueError):
    def __init__(
        self, *args: object, coverage_refusal_reason: CoverageRefusalReason | None = None
    ) -> None:
        if coverage_refusal_reason is not None and not isinstance(
            coverage_refusal_reason, CoverageRefusalReason
        ):
            raise TypeError("coverage refusal requires a typed reason")
        self.coverage_refusal_reason = coverage_refusal_reason
        super().__init__(*args)


class WorkerPluginSetupUnavailable(WorkerExecutionError):
    """Frozen plugin setup failed; suspend without closing or automatic retry."""


class WorkerAuthoritySetupUnavailable(WorkerExecutionError):
    """No model dispatch occurred; retain the Turn and require explicit reconciliation."""

    def __init__(self, reason_code: str = "host_authority_unavailable") -> None:
        if reason_code not in {"host_authority_unavailable", "host_authority_denied"}:
            raise ValueError("invalid Host startup refusal")
        self.reason_code = reason_code
        super().__init__(reason_code)


class RetryableWorkerSetupError(WorkerExecutionError):
    """Transient setup failure leaves the Session resumable."""


class CompletionRecoveryPending(RetryableWorkerSetupError):
    """Close recovery must defer; never retry model execution or write setup failure."""


def log_worker_failure(kind: str, stage: str, session_id: object, exc: BaseException) -> None:
    logger.exception(
        "%s stage=%s session=%s error_type=%s",
        kind,
        stage,
        session_id,
        type(exc).__name__,
    )


def exception_attempt_result(exc: Exception, metadata: dict[str, object]) -> HarnessAttemptResult:
    """Classify an unhandled exception into a terminal or recoverable result.

    CTX-ART-01: a capsule validation error that escapes the persistence
    fallback is a recovery signal, not a model execution failure. It must
    suspend (recoverable) rather than fail (terminal).
    """
    if isinstance(exc, PluginAuthorityUnavailable):
        return HarnessAttemptResult(
            outcome=HarnessAttemptOutcome.SUSPENDED,
            summary="Accepted plugin authority is unavailable; execution suspended.",
            metadata={**metadata, "stop_reason": PLUGIN_UNAVAILABLE, "retryable": False},
        )
    if isinstance(exc, ProviderContinuationUncertainError):
        return HarnessAttemptResult(
            outcome=HarnessAttemptOutcome.SUSPENDED,
            summary="provider continuation outcome is uncertain; automatic fallback refused",
            metadata={
                **metadata,
                "stop_reason": "provider_continuation_uncertain",
                "retryable": False,
            },
        )
    if isinstance(exc, WorkerCommitConfirmationPending):
        return HarnessAttemptResult(
            outcome=HarnessAttemptOutcome.SUSPENDED,
            summary="execution commit awaits confirmation; automatic replay refused",
            metadata={
                **metadata,
                "stop_reason": "execution_commit_confirmation_pending",
                "retryable": False,
            },
        )
    if isinstance(exc, WorkerProgressTimeout):
        return HarnessAttemptResult(
            outcome=HarnessAttemptOutcome.FAILED,
            summary="execution progress storage unavailable",
            metadata={
                **metadata,
                "stop_reason": "execution_progress_unavailable",
                "progress_stage": exc.stage,
            },
        )
    if isinstance(exc, RuntimeCapabilityError):
        return HarnessAttemptResult(
            outcome=HarnessAttemptOutcome.FAILED,
            summary="execution sandbox unavailable",
            metadata={**metadata, "stop_reason": "runtime_unavailable", "retryable": False},
        )
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
    if isinstance(exc, ModelProviderError):
        return HarnessAttemptResult(
            outcome=HarnessAttemptOutcome.FAILED,
            summary="model provider request failed",
            metadata={**metadata, "stop_reason": "model_provider_failed", "retryable": False},
        )
    reason = None
    if isinstance(exc, ExecutionAuthorityResolutionError):
        reason = "execution_authority_unavailable"
    elif isinstance(
        exc,
        psycopg.errors.LockNotAvailable
        | psycopg.errors.DeadlockDetected
        | psycopg.errors.SerializationFailure,
    ):
        reason = "execution_storage_contention"
    elif isinstance(exc, psycopg.OperationalError | psycopg.errors.QueryCanceled):
        reason = "execution_storage_unavailable"
    if reason is not None:
        # No model/tool replay: an unavailable authority or storage commit is not
        # proof of non-execution. Preserve facts and require explicit reconciliation.
        return HarnessAttemptResult(
            outcome=HarnessAttemptOutcome.SUSPENDED,
            summary="execution suspended: " + reason,
            metadata={**metadata, "stop_reason": reason, "retryable": False},
        )
    return HarnessAttemptResult(
        outcome=HarnessAttemptOutcome.FAILED,
        summary="execution failed",
        metadata={**metadata, "stop_reason": "execution_failed", "retryable": False},
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
    public_detail = isinstance(
        exc,
        ContextCapsuleValidationError
        | ContextWindowExceededError
        | ModelResponseRejectedError
        | ModelProviderError,
    )
    resumed_metadata = getattr(clarification or continuation, "metadata", None)
    metadata: dict[str, object] = {
        **(continuation_metadata(resumed_metadata) if isinstance(resumed_metadata, dict) else {}),
        "stop_reason": "model_execution_failed",
        "error_type": error_type,
        "model_calls_used": (model_calls or 0) + 1 + response_repair_count,
        "tool_calls_executed": tool_calls or 0,
        "error_message": (
            raw_error or f"{error_type} (no detail was provided)"
            if public_detail
            else f"{error_type} (details withheld)"
        ),
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
                **(
                    {"token_breakdown_v2": exc.plan.token_breakdown_v2.as_payload()}
                    if exc.plan.token_breakdown_v2 is not None
                    else {}
                ),
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
def sequence_race_guard(context: str, *, recovery: bool = False) -> Iterator[None]:
    """A lost durable sequence race means the snapshot is stale.

    The caller re-recovers once instead of raising past the Worker
    boundary (ADR-026 §5). Recovery-only writes defer instead of re-entering execution.
    """
    from zebra_agent_worker.execution_preflight import (  # noqa: PLC0415
        StaleExecutionSnapshot,
    )

    try:
        yield
    except ValueError as exc:
        if is_sequence_race(exc):
            if recovery:
                raise CompletionRecoveryPending(context) from exc
            raise StaleExecutionSnapshot(context) from exc
        raise
