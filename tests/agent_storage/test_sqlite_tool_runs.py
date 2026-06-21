from datetime import UTC, datetime
from pathlib import Path

from agent_core.domain.identifiers import new_session_id
from agent_core.domain.tool_runs import ToolRunRecord
from agent_storage import SQLiteToolRunStore


def test_sqlite_tool_run_store_upserts_and_lists_records(tmp_path: Path) -> None:
    store = SQLiteToolRunStore(tmp_path / "tool-runs.db")
    session_id = new_session_id()
    created_at = datetime(2026, 6, 22, 0, 20, tzinfo=UTC)
    first = ToolRunRecord(
        session_id=session_id,
        sequence=8,
        tool_name="tests.run",
        status="executed",
        idempotency_key="tool-run-8",
        output="ok",
        artifact_uri="file:///tmp/report.txt",
        created_at=created_at,
    )
    updated = first.model_copy(update={"output": "updated ok"})

    store.upsert(first)
    store.upsert(updated)

    assert store.list_for_session(session_id) == [updated]
