"""Slow durable boundaries are visible without recording arguments or identities."""

from contextlib import nullcontext
from types import SimpleNamespace

import pytest
from zebra_agent_worker import execution_events


@pytest.mark.parametrize("fail", [False, True])
def test_slow_mutation_reports_admission_and_execution_without_payload(monkeypatch, caplog, fail):
    clock = iter((10.0, 10.1, 10.6))
    monkeypatch.setattr(execution_events, "monotonic", lambda: next(clock))

    @execution_events._serialized
    def operation(recorder, private):
        if fail:
            raise ValueError("original error")
        return private

    recorder = SimpleNamespace(mutation=nullcontext)
    if fail:
        with pytest.raises(ValueError, match="original error"):
            operation(recorder, "private payload")
    else:
        assert operation(recorder, "private payload") == "private payload"
    assert "slow_worker_mutation operation=operation" in caplog.text
    assert "operation_ms=500" in caplog.text
    assert "private payload" not in caplog.text
