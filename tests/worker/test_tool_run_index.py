from datetime import UTC, datetime
from pathlib import Path

from agent_core.domain.events import EventActor, EventType, SessionEvent
from agent_core.domain.identifiers import new_session_id
from agent_storage import SQLiteToolRunStore
from zebra_agent_worker import ToolRunIndexer


def test_tool_run_indexer_indexes_tool_execution_event(tmp_path: Path) -> None:
    store = SQLiteToolRunStore(tmp_path / "tool-runs.db")
    event = SessionEvent.create(
        session_id=new_session_id(),
        sequence=5,
        event_type=EventType.TOOL_EXECUTION_COMPLETED,
        actor=EventActor.TOOL,
        payload={
            "attempt_number": 1,
            "tool_name": "tests.run",
            "status": "executed",
            "output": "ok",
            "metadata": {"artifact_uri": "file:///tmp/report.txt"},
        },
        idempotency_key="tool-run-5",
        created_at=datetime(2026, 6, 22, 0, 25, tzinfo=UTC),
    )

    record = ToolRunIndexer(store).index_event(event)

    assert record is not None
    assert record.tool_name == "tests.run"
    assert record.artifact_uri == "file:///tmp/report.txt"
    assert store.list_for_session(event.session_id) == [record]
