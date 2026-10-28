"""Infrastructure failures retain evidence and never request execution replay."""

import psycopg
import pytest
from agent_core.domain.execution_authority import ExecutionAuthorityResolutionError
from agent_core.harness.models import HarnessAttemptOutcome
from agent_integrations.model_errors import ModelProviderError
from zebra_agent_worker.execution_errors import error_metadata, exception_attempt_result


@pytest.mark.parametrize(
    ("error", "reason", "outcome"),
    [
        (
            psycopg.errors.LockNotAvailable,
            "execution_storage_contention",
            HarnessAttemptOutcome.SUSPENDED,
        ),
        (
            psycopg.errors.DeadlockDetected,
            "execution_storage_contention",
            HarnessAttemptOutcome.SUSPENDED,
        ),
        (
            psycopg.errors.SerializationFailure,
            "execution_storage_contention",
            HarnessAttemptOutcome.SUSPENDED,
        ),
        (
            psycopg.errors.QueryCanceled,
            "execution_storage_unavailable",
            HarnessAttemptOutcome.SUSPENDED,
        ),
        (
            psycopg.OperationalError,
            "execution_storage_unavailable",
            HarnessAttemptOutcome.SUSPENDED,
        ),
        (
            ExecutionAuthorityResolutionError,
            "execution_authority_unavailable",
            HarnessAttemptOutcome.SUSPENDED,
        ),
        (ValueError, "execution_failed", HarnessAttemptOutcome.FAILED),
    ],
)
def test_classification_preserves_private_details_and_disallows_replay(error, reason, outcome):
    exc = error("private endpoint, credential and SQL")
    result = exception_attempt_result(exc, error_metadata(exc, None, None))
    assert result.outcome is outcome
    assert result.metadata["stop_reason"] == reason
    assert result.metadata["retryable"] is False
    assert "model execution failed" != result.summary
    assert "private" not in str(result)


def test_nonretryable_provider_failure_is_explicit():
    exc = ModelProviderError("invalid_provider_response", retryable=False)
    result = exception_attempt_result(exc, error_metadata(exc, None, None))
    assert result.outcome is HarnessAttemptOutcome.FAILED
    assert result.metadata["stop_reason"] == "model_provider_failed"
    assert result.metadata["normalized_error"] == "invalid_provider_response"
    assert result.metadata["retryable"] is False


@pytest.mark.parametrize(
    "failure", [psycopg.errors.LockNotAvailable, ExecutionAuthorityResolutionError]
)
def test_actual_worker_pauses_without_ready_queue_replay(tmp_path, monkeypatch, failure):
    from agent_core.domain.events import EventType
    from agent_core.domain.sessions import SessionStatus
    from agent_storage import SQLiteEventStore, SQLiteLeaseStore, SQLiteProjectionStore

    from tests.worker.test_clarification_continuation import NOW, _execution_service, _seed_session

    class NoNetworkGateway:
        calls = 0

        def complete(self, *args, **kwargs):
            self.calls += 1
            raise failure("private execution detail")

    gateway = NoNetworkGateway()
    monkeypatch.setattr(
        "zebra_agent_worker.execution.build_model_gateway", lambda settings: gateway
    )
    database = tmp_path / "infrastructure.sqlite"
    session_id = _seed_session(database, tmp_path)
    result = _execution_service(database).execute_session(
        session_id,
        worker_id="isolated-worker",
        executed_at=NOW,
    )
    assert result.session.status is SessionStatus.SUSPENDED
    assert result.attempt_result.metadata["retryable"] is False
    assert gateway.calls == 1
    assert SQLiteLeaseStore(database).get(session_id) is None
    assert not SQLiteProjectionStore(database).list_ready_sessions(limit=10)
    events = SQLiteEventStore(database).list_for_session(session_id)
    assert sum(e.event_type is EventType.SESSION_SUSPENDED for e in events) == 1
    assert not any(
        e.event_type in {EventType.SESSION_FAILED, EventType.SESSION_COMPLETED} for e in events
    )
