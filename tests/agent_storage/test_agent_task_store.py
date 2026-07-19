from pathlib import Path

from agent_core.application import SessionBootstrapCommand, SessionBootstrapService
from agent_core.application.workspace_projection import rebuild_workspace
from agent_core.domain.agent_tasks import RolloverReason
from agent_core.domain.identifiers import TaskId
from agent_core.domain.tool_profiles import ToolProfile
from agent_storage import (
    SQLiteAgentTaskStore,
    SQLiteEventStore,
    SQLiteProjectionStore,
    SQLiteWorkspaceProjectionStore,
)


def test_task_store_backfills_root_and_keeps_monotonic_cross_segment_events(
    tmp_path: Path,
) -> None:
    database = tmp_path / "tasks.sqlite"
    root = _bootstrap(database, tmp_path / "root", "Root")
    child = _bootstrap(database, tmp_path / "child", "Child")
    store = SQLiteAgentTaskStore(database)
    task = store.ensure_for_session(root.session.session_id)

    assert str(task.task_id) == str(root.session.session_id)
    updated = store.attach_segment(
        task.task_id,
        child.session.session_id,
        predecessor_id=root.session.session_id,
        reason=RolloverReason.TERMINAL_FOLLOW_UP,
    )
    events = store.read_events(updated.task_id, -1)

    assert updated.active_segment_id == child.session.session_id
    assert [segment.segment_index for segment in store.segments(updated.task_id)] == [0, 1]
    assert [event.task_sequence for event in events] == list(range(len(events)))
    assert {event.segment_id for event in events} == {
        root.session.session_id,
        child.session.session_id,
    }
    assert store.get_task(TaskId(root.session.session_id)) == updated.model_copy(
        update={"current_sequence": len(events) - 1}
    )


def _bootstrap(database: Path, workspace: Path, title: str):
    result = SessionBootstrapService().build(
        SessionBootstrapCommand(
            title=title,
            user_input=title,
            workspace_root=workspace,
            policy_profile="workspace_write",
            tool_profile=ToolProfile.CODING,
            network_profile="none",
        )
    )
    events = SQLiteEventStore(database)
    for event in result.events:
        events.append(event)
    SQLiteProjectionStore(database).save_session(result.session)
    SQLiteWorkspaceProjectionStore(database).save_workspace(rebuild_workspace(list(result.events)))
    return result
