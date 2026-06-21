from datetime import UTC, datetime
from pathlib import Path

from agent_core.domain.events import EventActor, EventType, SessionEvent
from agent_core.domain.identifiers import new_session_id
from agent_storage import SQLiteModelCallStore
from zebra_agent_worker import ModelCallIndexer


def test_model_call_indexer_indexes_model_response_event(tmp_path: Path) -> None:
    store = SQLiteModelCallStore(tmp_path / "model-calls.db")
    event = SessionEvent.create(
        session_id=new_session_id(),
        sequence=3,
        event_type=EventType.MODEL_RESPONSE_RECEIVED,
        actor=EventActor.HARNESS,
        payload={
            "attempt_number": 1,
            "assistant_message": "I will inspect README before running tests.",
            "tool_call_count": 1,
            "provider": "openai",
            "model_name": "gpt-5-codex",
            "input_tokens": 120,
            "output_tokens": 36,
            "total_tokens": 156,
            "latency_ms": 850,
            "cache_hit": True,
            "cost_usd": 0.024,
        },
        created_at=datetime(2026, 6, 22, 1, 10, tzinfo=UTC),
    )

    record = ModelCallIndexer(store).index_event(event)

    assert record is not None
    assert record.provider == "openai"
    assert record.model_name == "gpt-5-codex"
    assert record.cache_hit is True
    assert record.tool_call_count == 1
    assert store.list_for_session(event.session_id) == [record]
