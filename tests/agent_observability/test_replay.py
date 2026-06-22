from pathlib import Path

import pytest
from agent_core.domain.events import EventType
from agent_observability import (
    AuditRecord,
    CostSummary,
    JsonlTraceStore,
    LocalReplayRunner,
    TraceRecord,
)


def _trace(session_id: str = "session-1", event_count: int = 2) -> TraceRecord:
    return TraceRecord(
        session_id=session_id,
        event_count=event_count,
        tool_result_count=1,
        cost=CostSummary(
            model_calls=1,
            input_tokens=10,
            output_tokens=5,
            total_tokens=15,
            cost_usd=0.02,
        ),
        audit=(
            AuditRecord(
                sequence=0,
                event_type=EventType.SESSION_CREATED,
                actor="system",
                summary="system:session_created",
            ),
            AuditRecord(
                sequence=1,
                event_type=EventType.TOOL_EXECUTION_COMPLETED,
                actor="tool",
                summary="tool:tool_execution_completed",
            ),
        ),
    )


def test_local_replay_runner_replays_trace_summary() -> None:
    result = LocalReplayRunner().replay(_trace())

    assert result.session_id == "session-1"
    assert result.event_count == 2
    assert result.tool_result_count == 1
    assert result.audit_steps == 2
    assert result.model_calls == 1
    assert result.total_tokens == 15
    assert result.cost_usd == 0.02


def test_local_replay_runner_replays_store_in_order(tmp_path: Path) -> None:
    store = JsonlTraceStore(tmp_path / "traces.jsonl")
    store.append(_trace("session-1"))
    store.append(_trace("session-2"))

    results = LocalReplayRunner().replay_store(store)

    assert [result.session_id for result in results] == ["session-1", "session-2"]


def test_local_replay_runner_returns_empty_for_empty_store(tmp_path: Path) -> None:
    store = JsonlTraceStore(tmp_path / "missing.jsonl")

    assert LocalReplayRunner().replay_store(store) == ()


def test_local_replay_runner_rejects_zero_event_trace() -> None:
    trace = TraceRecord(
        session_id="session-empty",
        event_count=0,
        tool_result_count=0,
        cost=CostSummary(),
        audit=(),
    )

    with pytest.raises(ValueError, match="at least one traced event"):
        LocalReplayRunner().replay(trace)
