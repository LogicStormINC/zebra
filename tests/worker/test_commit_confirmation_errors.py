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


def test_worker_commit_retries_explicit_lock_then_confirms_uncertain_ack(monkeypatch):
    from types import SimpleNamespace
    from unittest.mock import Mock

    from agent_storage.postgres import worker_commit_confirmation as commits
    from psycopg.errors import LockNotAvailable

    event, session, workspace, authority = (object() for _ in range(4))
    result = object()
    store = SimpleNamespace(_database=SimpleNamespace(_dsn="db", deployment_namespace="test"))
    write = Mock(side_effect=[LockNotAvailable(), TimeoutError("uncertain acknowledgement")])
    confirm = Mock(return_value=result)
    monkeypatch.setattr(commits, "_confirm", confirm)
    assert commits.confirm_on_timeout(write)(
        store, event, session, workspace, authority=authority
    ) is result
    assert write.call_count == 2 and write.call_args_list[0] == write.call_args_list[1]
    confirm.assert_called_once_with(store, event, session, workspace, authority)
