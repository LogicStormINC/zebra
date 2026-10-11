"""Worker rejection diagnostics preserve the allowlist, not exception causes."""

import pytest
from agent_core.ports.model_gateway import ModelResponseRejectedError
from zebra_agent_worker.execution_errors import error_metadata, exception_attempt_result


def test_repair_and_worker_metadata_preserve_rule_without_private_cause() -> None:
    error = ModelResponseRejectedError(
        "invalid_response_shape",
        phase="response_payload",
        retryable=False,
        validation_rule="tool_call_id_nonblank",
    )
    error.__cause__ = ValueError("secret-provider-response-and-key")
    repaired = error.after_repairs(1, initial_reason=error.reason)
    metadata = error_metadata(repaired, None, None)
    assert metadata["validation_rule"] == "tool_call_id_nonblank"
    assert metadata["retryable"] is False
    assert metadata["response_repair_count"] == 1
    assert metadata["model_calls_used"] == 2
    assert "secret" not in str(metadata)
    result = exception_attempt_result(repaired, metadata)
    assert result.metadata["validation_rule"] == "tool_call_id_nonblank"
    assert result.metadata["stop_reason"] == "model_response_repair_exhausted"


def test_old_errors_do_not_gain_diagnostic_metadata() -> None:
    error = ModelResponseRejectedError(
        "invalid_response_shape", phase="response_payload", retryable=True
    )
    assert "validation_rule" not in error.metadata()
    assert "validation_rule" not in error_metadata(error, None, None)


def test_untrusted_validation_rule_rejected_without_echo() -> None:
    with pytest.raises(ValueError, match="must be allowlisted") as caught:
        ModelResponseRejectedError(
            "invalid_response_shape",
            phase="response_payload",
            retryable=True,
            validation_rule="private-provider-payload",
        )
    assert "private" not in str(caught.value)
