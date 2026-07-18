from pathlib import Path

import pytest
from agent_core.domain.events import EventType
from agent_observability import (
    AuditRecord,
    CostSummary,
    JsonlTraceStore,
    ProviderModelCallTrace,
    TraceRecord,
)


def _trace(session_id: str = "session-1") -> TraceRecord:
    return TraceRecord(
        session_id=session_id,
        event_count=2,
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
        model_calls=(
            ProviderModelCallTrace(
                sequence=1,
                profile_id="deepseek-v4-flash-executor-v1",
                prompt_version="zebra-deepseek-chat-v1",
                tool_schema_bytes=64,
                tool_schema_hash="schema-hash",
                stable_prefix_hash="prefix-hash",
                input_tokens=10,
                output_tokens=5,
                reasoning_tokens=2,
                prompt_cache_hit_tokens=8,
                prompt_cache_miss_tokens=2,
                cost_usd=0.02,
            ),
        ),
    )


def test_jsonl_trace_store_appends_and_lists_traces(tmp_path: Path) -> None:
    store = JsonlTraceStore(tmp_path / "traces" / "local.jsonl")

    store.append(_trace("session-1"))
    store.append(_trace("session-2"))

    traces = store.list()

    assert [trace.session_id for trace in traces] == ["session-1", "session-2"]
    assert traces[0].cost.total_tokens == 15
    assert traces[1].audit[1].event_type is EventType.TOOL_EXECUTION_COMPLETED
    assert traces[0].model_calls[0].stable_prefix_hash == "prefix-hash"
    assert traces[0].model_calls[0].reasoning_tokens == 2
    assert traces[0].model_calls[0].cost_usd == 0.02


def test_jsonl_trace_store_lists_empty_when_file_is_missing(tmp_path: Path) -> None:
    assert JsonlTraceStore(tmp_path / "missing.jsonl").list() == ()


def test_jsonl_trace_store_rejects_directory_path(tmp_path: Path) -> None:
    store = JsonlTraceStore(tmp_path)

    with pytest.raises(ValueError, match="directory"):
        store.append(_trace())
