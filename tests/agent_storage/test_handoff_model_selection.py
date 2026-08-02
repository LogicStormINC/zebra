from pathlib import Path

from agent_core.domain.events import EventType
from agent_storage import SQLiteEventStore, SQLiteSessionHandoffStore
from test_session_handoffs import _prepared_commit, _seed_completed_source


def test_handoff_carries_root_task_model_selection_into_child_task(tmp_path: Path) -> None:
    database_path = tmp_path / "model-handoff.db"
    source = _seed_completed_source(database_path, tmp_path, model_id="deepseek-text")
    handoffs = SQLiteSessionHandoffStore(database_path)
    operation, request = _prepared_commit(handoffs, source)

    handoffs.commit(request)

    child_events = SQLiteEventStore(database_path).list_for_session(operation.target_session_id)
    prepared = next(event for event in child_events if event.event_type is EventType.TASK_PREPARED)
    assert prepared.payload["model_id"] == "deepseek-text"
