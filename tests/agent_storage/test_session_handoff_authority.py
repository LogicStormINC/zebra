from pathlib import Path

from agent_core.domain.events import EventType
from agent_storage import (
    SQLiteEventStore,
    SQLiteSessionHandoffStore,
    SQLiteWorkspaceProjectionStore,
)

from tests.agent_storage.test_session_handoffs import (
    NOW,
    _prepared_commit,
    _seed_completed_source,
)


def test_handoff_threads_skill_components_into_child_task_and_authority(
    tmp_path: Path,
) -> None:
    database_path = tmp_path / "handoff.db"
    source = _seed_completed_source(database_path, tmp_path)
    handoffs = SQLiteSessionHandoffStore(database_path)
    workspace_store = SQLiteWorkspaceProjectionStore(database_path)
    workspace = workspace_store.get_workspace(source)
    assert workspace is not None

    facts_without = handoffs.inspect_source_facts(source, at=NOW)
    workspace_store.save_workspace(
        workspace.model_copy(update={"skill_components": ("Review", "evidence")})
    )
    facts_with = handoffs.inspect_source_facts(source, at=NOW)
    # skill_components participates in the authority revision hash.
    assert facts_with.authority_revision != facts_without.authority_revision

    operation, request = _prepared_commit(handoffs, source)
    handoffs.commit(request)

    child_events = SQLiteEventStore(database_path).list_for_session(operation.target_session_id)
    prepared = next(event for event in child_events if event.event_type is EventType.TASK_PREPARED)
    # the child TASK_PREPARED payload carries the explicit skill_components section.
    assert prepared.payload["skill_components"] == ["Review", "evidence"]

    child_workspace = workspace_store.get_workspace(operation.target_session_id)
    assert child_workspace is not None
    assert child_workspace.skill_components == ("Review", "evidence")
