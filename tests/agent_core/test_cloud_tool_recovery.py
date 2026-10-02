"""Fault injection at the shared gateway boundary and its model-facing contract."""

from concurrent.futures import CancelledError
from datetime import UTC, datetime

import pytest
from agent_core.domain.identifiers import new_tool_call_id
from agent_core.domain.tools import ToolCall, ToolCallStatus, ToolResult
from agent_core.harness.model_step_support import tool_result_content
from agent_core.harness.orchestration_events import continuation_metadata
from agent_core.harness.protocol_invariants import HarnessInvariantError
from agent_core.harness.tool_recovery import (
    can_retry_read,
    execute_observed,
    normalize_failure,
    record_recovery,
)


def call(name: str = "web.fetch") -> ToolCall:
    return ToolCall(
        tool_call_id=new_tool_call_id(),
        name=name,
        arguments={"url": "https://example.com"},
        created_at=datetime.now(UTC),
    )


class FaultGateway:
    read_only_tools = frozenset({"web.fetch"})

    def __init__(self, error: Exception) -> None:
        self.error = error

    def execute(self, tool_call: ToolCall) -> ToolResult:
        raise self.error


@pytest.mark.parametrize(
    "error",
    [
        ValueError("secret=private"),
        FileNotFoundError(),
        PermissionError(),
        TimeoutError(),
        ConnectionError(),
    ],
)
def test_expected_errors_are_model_observations(error: Exception) -> None:
    result = execute_observed(FaultGateway(error), call())
    assert result.status is ToolCallStatus.FAILED
    assert "private" not in tool_result_content(result)
    for key in ("code", "category", "execution_state", "recovery_hint", "retryable"):
        assert key in tool_result_content(result)


@pytest.mark.parametrize(
    "error",
    [
        CancelledError(),
        HarnessInvariantError("broken"),
        AssertionError(),
        RuntimeError("internal bug"),
    ],
)
def test_internal_errors_and_cancellation_are_not_recoverable(error: Exception) -> None:
    with pytest.raises(type(error)):
        execute_observed(FaultGateway(error), call())


def test_read_retries_are_bounded_and_survive_continuation() -> None:
    request = call()
    result = execute_observed(FaultGateway(TimeoutError()), request)
    metadata: dict[str, object] = {}
    for expected in (True, True, False):
        metadata = record_recovery(metadata, request, result)
        metadata = continuation_metadata(metadata)
        assert can_retry_read(request, metadata) is expected


def test_uncertain_write_is_never_retried() -> None:
    request = call("files.write")
    result = execute_observed(FaultGateway(TimeoutError()), request)
    assert result.metadata["execution_state"] == "unknown"
    assert result.metadata["retryable"] is False
    assert "receipt" in str(result.metadata["recovery_hint"])
    assert not can_retry_read(request, record_recovery({}, request, result))


def test_retry_after_is_not_immediately_reissued() -> None:
    request = call()
    result = normalize_failure(
        ToolResult(
            tool_call_id=request.tool_call_id,
            status=ToolCallStatus.FAILED,
            metadata={"retryable": True, "retry_after_seconds": 10},
        ),
        read_only=True,
    )
    assert not can_retry_read(request, record_recovery({}, request, result))


def test_success_removes_transient_retry_permission() -> None:
    request = call()
    result = execute_observed(FaultGateway(TimeoutError()), request)
    metadata = record_recovery({}, request, result)
    succeeded = ToolResult(tool_call_id=request.tool_call_id, status=ToolCallStatus.EXECUTED)
    assert not can_retry_read(request, record_recovery(metadata, request, succeeded))


def test_invalid_request_limit_is_not_reported_as_budget_exhaustion() -> None:
    from agent_core.harness.sequential_support import synthesis_required, synthesis_stop_reason

    metadata = {"invalid_tool_requests": 2}
    assert synthesis_required(None, 3, metadata)
    assert synthesis_stop_reason(True, metadata) == "invalid_tool_request_limit"
