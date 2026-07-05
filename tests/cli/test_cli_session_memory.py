from datetime import UTC, datetime
from pathlib import Path
from uuid import UUID

from agent_core.application import SessionBootstrapCommand, SessionBootstrapService
from agent_core.domain.events import EventActor, EventType, SessionEvent
from agent_core.domain.identifiers import MemoryId, SessionId
from agent_core.domain.memories import MemoryRecord, MemoryStatus, MemoryType, MemoryVisibility
from agent_core.domain.sessions import Session
from agent_storage import SQLiteEventStore, SQLiteMemoryStore, SQLiteProjectionStore
from zebra_agent_cli.cli import execute


def test_cli_memory_lists_repo_scoped_records(tmp_path: Path) -> None:
    database_path = tmp_path / "sessions.sqlite"
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    bootstrap = SessionBootstrapService().build(
        SessionBootstrapCommand(
            title="CLI memory",
            user_input="Inspect memories.",
            workspace_root=workspace.resolve(),
        )
    )
    for event in bootstrap.events:
        SQLiteEventStore(database_path).append(event)
    SQLiteProjectionStore(database_path).save_session(bootstrap.session)
    _append_procedure_source_event(database_path, bootstrap.session.session_id)
    record = _memory_record(
        str(workspace.resolve()),
        str(bootstrap.session.session_id),
        source_event_start=3,
        source_event_end=3,
    )
    SQLiteMemoryStore(database_path).upsert(record)

    result = execute(
        ["memory", str(bootstrap.session.session_id), "--database", str(database_path)]
    )

    assert result.command == "memory"
    assert result.payload == {
        "session_id": str(bootstrap.session.session_id),
        "database": str(database_path),
        "status": "ok",
        "repo_id": str(workspace.resolve()),
        "memories": [
            _memory_payload(
                record,
                source={
                    "kind": "tool",
                    "event_type": "tool_execution_completed",
                    "tool_name": "tests.run",
                    "source_event_start": 3,
                    "source_event_end": 3,
                    "captured_at": "2026-07-02T10:00:00+00:00",
                    "locator": "make check",
                    "cwd": ".",
                    "preset": "smoke",
                },
            )
        ],
    }


def test_cli_memory_includes_last_review_metadata(tmp_path: Path) -> None:
    database_path = tmp_path / "sessions.sqlite"
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    bootstrap = SessionBootstrapService().build(
        SessionBootstrapCommand(
            title="CLI memory",
            user_input="Inspect memories.",
            workspace_root=workspace.resolve(),
        )
    )
    for event in bootstrap.events:
        SQLiteEventStore(database_path).append(event)
    SQLiteProjectionStore(database_path).save_session(bootstrap.session)
    _append_procedure_source_event(database_path, bootstrap.session.session_id)
    record = _memory_record(str(workspace.resolve()), str(bootstrap.session.session_id)).model_copy(
        update={
            "status": MemoryStatus.EXPIRED,
            "source_event_start": 3,
            "source_event_end": 3,
        }
    )
    SQLiteMemoryStore(database_path).upsert(record)
    SQLiteEventStore(database_path).append(
        SessionEvent.create(
            session_id=bootstrap.session.session_id,
            sequence=4,
            event_type=EventType.MEMORY_REVIEW_RECORDED,
            actor=EventActor.HARNESS,
            payload={
                "memory_id": str(record.memory_id),
                "memory_type": record.memory_type.value,
                "previous_status": "confirmed",
                "status": "expired",
                "operator": "system",
                "reason": "stale after AGENTS.md refresh",
                "superseded_memory_ids": [],
                "duplicate_of_memory_id": None,
            },
            created_at=datetime(2026, 7, 3, 9, 30, tzinfo=UTC),
        )
    )

    result = execute(
        ["memory", str(bootstrap.session.session_id), "--database", str(database_path)]
    )

    assert result.payload["memories"] == [
        _memory_payload(
            record,
            source={
                    "kind": "tool",
                    "event_type": "tool_execution_completed",
                    "tool_name": "tests.run",
                    "source_event_start": 3,
                    "source_event_end": 3,
                    "captured_at": "2026-07-02T10:00:00+00:00",
                    "locator": "make check",
                    "cwd": ".",
                    "preset": "smoke",
            },
            last_review={
                "recorded_at": "2026-07-03T09:30:00+00:00",
                "previous_status": "confirmed",
                "status": "expired",
                "operator": "system",
                "reason": "stale after AGENTS.md refresh",
                "superseded_memory_ids": [],
                "duplicate_of_memory_id": None,
            },
        )
    ]


def test_cli_memory_reports_unavailable_without_workspace(tmp_path: Path) -> None:
    database_path = tmp_path / "sessions.sqlite"
    session = SQLiteProjectionStore(database_path).save_session(
        Session.create(title="No workspace")
    )

    result = execute(["memory", str(session.session_id), "--database", str(database_path)])

    assert result.payload == {
        "session_id": str(session.session_id),
        "database": str(database_path),
        "status": "memory_unavailable",
        "reason": "session workspace_root is unavailable",
    }


def test_cli_memory_reports_missing_session(tmp_path: Path) -> None:
    database_path = tmp_path / "sessions.sqlite"

    result = execute(
        [
            "memory",
            "00000000-0000-0000-0000-000000000001",
            "--database",
            str(database_path),
        ]
    )

    assert result.payload == {
        "session_id": "00000000-0000-0000-0000-000000000001",
        "database": str(database_path),
        "status": "not_found",
    }


def test_cli_memory_exposes_doc_read_source_provenance(tmp_path: Path) -> None:
    database_path = tmp_path / "sessions.sqlite"
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    bootstrap = SessionBootstrapService().build(
        SessionBootstrapCommand(
            title="CLI memory",
            user_input="Inspect memories.",
            workspace_root=workspace.resolve(),
        )
    )
    for event in bootstrap.events:
        SQLiteEventStore(database_path).append(event)
    SQLiteProjectionStore(database_path).save_session(bootstrap.session)
    _append_doc_source_event(database_path, bootstrap.session.session_id)
    record = _memory_record(
        str(workspace.resolve()),
        str(bootstrap.session.session_id),
        memory_type=MemoryType.PROJECT_RULE,
        text="Use the repo default commands: `make sync`, `make check`.",
        source_event_start=3,
        source_event_end=3,
    )
    SQLiteMemoryStore(database_path).upsert(record)
    result = execute(
        ["memory", str(bootstrap.session.session_id), "--database", str(database_path)]
    )

    assert result.payload["memories"] == [
        _memory_payload(
            record,
            source={
                "kind": "tool",
                "event_type": "tool_execution_completed",
                "tool_name": "files.read",
                "source_event_start": 3,
                "source_event_end": 3,
                "captured_at": "2026-07-02T10:05:00+00:00",
                "locator": "AGENTS.md",
            },
        )
    ]


def _memory_record(
    repo_id: str,
    source_session_id: str,
    *,
    memory_type: MemoryType = MemoryType.PROCEDURE,
    text: str = "rerun make check after memory wiring",
    source_event_start: int = 2,
    source_event_end: int = 2,
) -> MemoryRecord:
    created_at = datetime(2026, 7, 2, 10, 0, tzinfo=UTC)
    return MemoryRecord(
        memory_id=MemoryId(UUID("00000000-0000-0000-0000-000000000112")),
        memory_type=memory_type,
        text=text,
        confidence=0.9,
        status=MemoryStatus.CANDIDATE,
        visibility=MemoryVisibility.REPO,
        repo_id=repo_id,
        source_session_id=SessionId(UUID(source_session_id)),
        source_event_start=source_event_start,
        source_event_end=source_event_end,
        created_at=created_at,
        updated_at=created_at,
    )


def _memory_payload(
    record: MemoryRecord,
    *,
    source: dict[str, object] | None = None,
    last_review: dict[str, object] | None = None,
) -> dict[str, object]:
    return {
        **record.model_dump(mode="json"),
        "source": source,
        "last_review": last_review,
    }


def _append_procedure_source_event(database_path: Path, session_id: SessionId) -> None:
    SQLiteEventStore(database_path).append(
        SessionEvent.create(
            session_id=session_id,
            sequence=3,
            event_type=EventType.TOOL_EXECUTION_COMPLETED,
            actor=EventActor.TOOL,
            payload={
                "attempt_number": 1,
                "tool_name": "tests.run",
                "status": "executed",
                "output": "validated",
                "metadata": {
                    "command": ["make", "check"],
                    "cwd": ".",
                    "preset": "smoke",
                    "exit_code": 0,
                    "stderr": "",
                    "timed_out": False,
                },
            },
            created_at=datetime(2026, 7, 2, 10, 0, tzinfo=UTC),
        )
    )


def _append_doc_source_event(database_path: Path, session_id: SessionId) -> None:
    SQLiteEventStore(database_path).append(
        SessionEvent.create(
            session_id=session_id,
            sequence=3,
            event_type=EventType.TOOL_EXECUTION_COMPLETED,
            actor=EventActor.TOOL,
            payload={
                "attempt_number": 1,
                "tool_name": "files.read",
                "status": "executed",
                "output": "# Zebra Agent Repository Rules",
                "metadata": {
                    "path": "AGENTS.md",
                    "byte_count": 32,
                    "truncated": False,
                },
            },
            created_at=datetime(2026, 7, 2, 10, 5, tzinfo=UTC),
        )
    )
