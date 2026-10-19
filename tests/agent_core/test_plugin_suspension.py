"""Plugin revocation pairs a complete provider batch and never calls the model again."""

import pytest
from agent_core.domain.events import EventType
from agent_core.domain.plugin_authority import PLUGIN_UNAVAILABLE, PluginAuthorityUnavailable
from agent_core.harness import HarnessAttemptOutcome

from tests.agent_core.test_concurrent_tool_batches import _read, _run


@pytest.mark.parametrize("parallel", [1, 2])
def test_revoked_source_stops_serial_and_concurrent_batches(parallel: int) -> None:
    class Revoked:
        read_only_tools = frozenset({"files.read"})

        def execute(self, call):
            raise PluginAuthorityUnavailable("private backend credential detail")

    calls = (_read("a.txt", "call_a"), _read("b.txt", "call_b"))
    result, model = _run(calls, Revoked(), max_parallel=parallel)
    assert result.attempt_result.outcome is HarnessAttemptOutcome.SUSPENDED
    assert result.attempt_result.metadata["stop_reason"] == PLUGIN_UNAVAILABLE
    assert len(model.requests) == 1
    failed = [e for e in result.events if e.event_type is EventType.TOOL_EXECUTION_FAILED]
    assert [e.payload["tool_call_id"] for e in failed] == [str(c.tool_call_id) for c in calls]
    assert "private" not in str(failed)
    assert result.attempt_result.metadata["retryable"] is False
