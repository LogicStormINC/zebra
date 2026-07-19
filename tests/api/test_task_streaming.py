import asyncio
from pathlib import Path

from agent_core.application import SessionBootstrapCommand, SessionBootstrapService
from agent_core.application.workspace_projection import rebuild_workspace
from agent_core.domain.identifiers import TaskId
from agent_storage import (
    SQLiteAgentTaskStore,
    SQLiteEventStore,
    SQLiteProjectionStore,
    SQLiteWorkspaceProjectionStore,
)
from zebra_agent_api.session_streaming import tail_task_events


class _DisconnectedAfterReplay:
    def __init__(self) -> None:
        self.calls = 0

    async def is_disconnected(self) -> bool:
        self.calls += 1
        return self.calls > 1


def test_task_stream_uses_task_cursor_without_segment_identity(tmp_path: Path) -> None:
    database = tmp_path / "tasks.sqlite"
    bootstrap = SessionBootstrapService().build(
        SessionBootstrapCommand(title="Task stream", user_input="hello", workspace_root=tmp_path)
    )
    event_store = SQLiteEventStore(database)
    for event in bootstrap.events:
        event_store.append(event)
    SQLiteProjectionStore(database).save_session(bootstrap.session)
    SQLiteWorkspaceProjectionStore(database).save_workspace(
        rebuild_workspace(list(bootstrap.events))
    )
    task = SQLiteAgentTaskStore(database).ensure_for_session(bootstrap.session.session_id)

    async def collect() -> list[str]:
        return [
            chunk
            async for chunk in tail_task_events(
                database_path=database,
                task_id=TaskId(task.task_id),
                request=_DisconnectedAfterReplay(),  # type: ignore[arg-type]
                after_sequence=-1,
            )
        ]

    chunks = asyncio.run(collect())

    assert chunks
    assert all("segment_id" not in chunk for chunk in chunks)
    assert chunks[0].startswith("id: 0\nevent: task_event\n")
