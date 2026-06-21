from datetime import UTC, datetime
from pathlib import Path

from agent_core.domain.identifiers import new_session_id
from agent_core.domain.model_calls import ModelCallRecord
from agent_storage import SQLiteModelCallStore


def test_sqlite_model_call_store_upserts_and_lists_records(tmp_path: Path) -> None:
    store = SQLiteModelCallStore(tmp_path / "model-calls.db")
    session_id = new_session_id()
    created_at = datetime(2026, 6, 22, 1, 0, tzinfo=UTC)
    first = ModelCallRecord(
        session_id=session_id,
        sequence=4,
        provider="openai",
        model_name="gpt-5-codex",
        input_tokens=120,
        output_tokens=36,
        total_tokens=156,
        latency_ms=850,
        cache_hit=False,
        cost_usd=0.024,
        assistant_message="I will inspect the repo first.",
        tool_call_count=1,
        created_at=created_at,
    )
    updated = first.model_copy(update={"cache_hit": True, "latency_ms": 640})

    store.upsert(first)
    store.upsert(updated)

    assert store.list_for_session(session_id) == [updated]
