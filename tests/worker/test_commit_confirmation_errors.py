"""Uncertain commits pause execution without inventing success or allowing replay."""

from agent_core.harness.models import HarnessAttemptOutcome
from agent_core.ports.workspace_projection_store import WorkerCommitConfirmationPending
from zebra_agent_worker.execution_errors import error_metadata, exception_attempt_result


def test_commit_confirmation_failure_is_suspended_and_non_retryable():
    error = WorkerCommitConfirmationPending("private storage details")
    result = exception_attempt_result(error, error_metadata(error, None, None))
    assert result.outcome is HarnessAttemptOutcome.SUSPENDED
    assert result.metadata["stop_reason"] == "execution_commit_confirmation_pending"
    assert result.metadata["retryable"] is False
    assert "private storage details" not in str(result)
