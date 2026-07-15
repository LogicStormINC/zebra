from pathlib import Path

from agent_core.domain.events import EventActor, EventType, SessionEvent
from agent_core.domain.sessions import Session
from agent_storage import SQLiteEventStore, SQLiteProjectionStore
from zebra_agent_cli.cli import execute


def test_cli_stream_lists_persisted_events(tmp_path: Path) -> None:
    database_path = tmp_path / "sessions.sqlite"
    session = SQLiteProjectionStore(database_path).save_session(
        Session.create(title="CLI stream")
    )
    event_store = SQLiteEventStore(database_path)
    created = event_store.append(
        SessionEvent.create(
            session_id=session.session_id,
            sequence=0,
            event_type=EventType.SESSION_CREATED,
            actor=EventActor.USER,
            payload={"title": session.title},
        )
    )
    prepared = event_store.append(
        SessionEvent.create(
            session_id=session.session_id,
            sequence=1,
            event_type=EventType.TASK_PREPARED,
            actor=EventActor.HARNESS,
            payload={"title": session.title, "user_input": "stream me"},
        )
    )

    result = execute(["stream", str(session.session_id), "--database", str(database_path)])

    assert result.command == "stream"
    assert result.payload == {
        "session_id": str(session.session_id),
        "database": str(database_path),
        "status": "ok",
        "events": [
            {
                "event_id": str(created.event_id),
                "sequence": 0,
                "event_type": EventType.SESSION_CREATED.value,
                "actor": EventActor.USER.value,
                "created_at": created.created_at.isoformat(),
                "payload": {"title": session.title},
            },
            {
                "event_id": str(prepared.event_id),
                "sequence": 1,
                "event_type": EventType.TASK_PREPARED.value,
                "actor": EventActor.HARNESS.value,
                "created_at": prepared.created_at.isoformat(),
                "payload": {
                    "title": session.title,
                    "user_input": "stream me",
                    "workspace_root": None,
                    "policy_profile": None,
                    "tool_profile": None,
                    "max_attempts": None,
                    "max_model_calls": None,
                    "max_tool_calls": None,
                },
            },
        ],
    }


def test_cli_stream_returns_bootstrap_only_events(tmp_path: Path) -> None:
    database_path = tmp_path / "sessions.sqlite"
    session = SQLiteProjectionStore(database_path).save_session(
        Session.create(title="Bootstrap only")
    )
    event = SQLiteEventStore(database_path).append(
        SessionEvent.create(
            session_id=session.session_id,
            sequence=0,
            event_type=EventType.SESSION_CREATED,
            actor=EventActor.USER,
            payload={"title": session.title},
        )
    )

    result = execute(["stream", str(session.session_id), "--database", str(database_path)])

    assert result.payload["status"] == "ok"
    assert result.payload["events"] == [
        {
            "event_id": str(event.event_id),
            "sequence": 0,
            "event_type": EventType.SESSION_CREATED.value,
            "actor": EventActor.USER.value,
            "created_at": event.created_at.isoformat(),
            "payload": {"title": session.title},
        }
    ]


def test_cli_stream_reports_missing_session(tmp_path: Path) -> None:
    database_path = tmp_path / "sessions.sqlite"

    result = execute(
        [
            "stream",
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
