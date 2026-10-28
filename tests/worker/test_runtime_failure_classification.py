"""Infrastructure failure is neither model failure nor an automatic retry."""
from agent_core.harness.models import HarnessAttemptOutcome
from agent_core.ports.runtime import RuntimeCapabilityError
from zebra_agent_worker.execution_errors import error_metadata, exception_attempt_result


def test_runtime_failure_is_distinct_and_details_stay_private():
    error = RuntimeCapabilityError("private endpoint and engine stderr")
    result = exception_attempt_result(error, error_metadata(error, None, None))
    assert result.outcome is HarnessAttemptOutcome.FAILED
    assert result.summary == "execution sandbox unavailable"
    assert result.metadata["stop_reason"] == "runtime_unavailable"
    assert result.metadata["retryable"] is False
    assert "private endpoint" not in str(result.metadata)
