from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID

from agent_core.domain.events import EventActor, EventType, SessionEvent
from agent_core.domain.governed_memories import (
    GovernedMemoryEntry,
    canonical_governed_memory_content_hash,
    canonical_governed_memory_creation_key,
)
from agent_core.domain.identifiers import MemoryId, SessionId
from agent_core.domain.memories import MemoryRecord, MemoryStatus, MemoryType, MemoryVisibility
from agent_storage.postgres.context_materialization import _exclude_legacy_tool_commands


def test_cloud_recall_excludes_only_source_verified_legacy_commands() -> None:
    now = datetime(2026, 9, 30, tzinfo=UTC)
    session_id = SessionId(UUID(int=300))
    source = SessionEvent.create(
        session_id=session_id,
        sequence=7,
        event_type=EventType.TOOL_EXECUTION_COMPLETED,
        actor=EventActor.TOOL,
        payload={
            "tool_name": "command.run",
            "status": "executed",
            "attempt_number": 1,
            "output": "",
            "metadata": {"command": ["uv", "venv", ".venv-chart"], "cwd": "."},
        },
        created_at=now,
    )

    def entry(index: int, text: str, sourced: bool) -> GovernedMemoryEntry:
        record = MemoryRecord(
            memory_id=MemoryId(UUID(int=index)),
            memory_type=MemoryType.PROCEDURE,
            text=text,
            confidence=0.8,
            status=MemoryStatus.CONFIRMED,
            visibility=MemoryVisibility.USER,
            user_id="user-1",
            source_session_id=session_id if sourced else None,
            source_event_start=7 if sourced else None,
            source_event_end=7 if sourced else None,
            created_at=now,
            updated_at=now,
        )
        return GovernedMemoryEntry(
            deployment_namespace="test",
            record=record,
            revision=1,
            creation_key=canonical_governed_memory_creation_key(record),
            content_digest=canonical_governed_memory_content_hash(record),
        )

    old = entry(1, "Run `uv venv .venv-chart` from `.`.", True)
    manual = entry(2, "Run `uv venv .venv-chart` from `.`.", False)
    useful = entry(3, "Use uv for isolated setup.", True)

    class Connection:
        def execute(self, sql: str, params: tuple[object, ...]) -> Connection:
            assert "deployment_namespace = %s" in sql
            assert params == ("test", session_id, 7)
            return self

        def fetchall(self) -> list[dict[str, object]]:
            return [source.model_dump(mode="python")]

    assert _exclude_legacy_tool_commands(Connection(), "test", (old, manual, useful)) == (
        manual,
        useful,
    )
