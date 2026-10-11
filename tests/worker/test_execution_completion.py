"""Secondary cleanup faults must not replace execution or cancellation truth."""

import asyncio
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from agent_core.harness.models import HarnessAttemptOutcome, HarnessAttemptResult
from zebra_agent_worker import execution_completion
from zebra_agent_worker.execution_events import ExecutionInterrupted


@pytest.mark.parametrize("outcome", [HarnessAttemptOutcome.FAILED, HarnessAttemptOutcome.SUSPENDED])
def test_cleanup_preserves_original_outcome_and_metadata(monkeypatch, outcome):
    original = HarnessAttemptResult(
        outcome=outcome,
        summary="original provider or budget outcome",
        metadata={"stop_reason": "original", "model_calls_used": 7},
    )
    monkeypatch.setattr(execution_completion, "run_continuation", Mock(return_value=original))
    release = Mock(return_value=RuntimeError("gateway cleanup"))
    orchestrator = SimpleNamespace(close=Mock(side_effect=ValueError("timer cleanup")))
    result = execution_completion.run_worker_continuation(
        orchestrator,
        object(),
        continuation=None,
        clarification=None,
        child_wakeup=None,
        client_effect=None,
        release_gateway=release,
    )
    assert result.outcome is outcome
    assert result.summary == original.summary
    assert result.metadata["stop_reason"] == "original"
    assert result.metadata["model_calls_used"] == 7
    assert result.metadata["cleanup_error_type"] == "ValueError"
    orchestrator.close.assert_called_once()
    release.assert_called_once()


@pytest.mark.parametrize("error", [asyncio.CancelledError("cancel"), ExecutionInterrupted("fence")])
def test_cancellation_survives_cleanup_and_always_releases_gateway(monkeypatch, error):
    monkeypatch.setattr(execution_completion, "run_continuation", Mock(side_effect=error))
    release = Mock(return_value=RuntimeError("gateway cleanup"))
    orchestrator = SimpleNamespace(close=Mock(side_effect=ValueError("timer cleanup")))
    with pytest.raises(type(error)) as caught:
        execution_completion.run_worker_continuation(
            orchestrator,
            object(),
            continuation=None,
            clarification=None,
            child_wakeup=None,
            client_effect=None,
            release_gateway=release,
        )
    assert caught.value is error
    assert any("ValueError" in note for note in error.__notes__)
    assert any("RuntimeError" in note for note in error.__notes__)
    orchestrator.close.assert_called_once()
    release.assert_called_once()
