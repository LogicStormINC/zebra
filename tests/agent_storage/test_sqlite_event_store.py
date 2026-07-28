from datetime import UTC, datetime
from pathlib import Path

import pytest
from agent_core.application.session_projection import rebuild_session
from agent_core.domain.events import EventActor, EventType, SessionEvent
from agent_core.domain.identifiers import new_session_id
from agent_storage import SQLiteEventStore, SQLiteProjectionStore
from agent_storage.event_rows import SessionEventIdempotencyConflictError


def test_sqlite_event_store_appends_and_lists_session_events(tmp_path: Path) -> None:
    store = SQLiteEventStore(tmp_path / "events.db")
    session_id = new_session_id()
    created_at = datetime(2026, 6, 19, 23, 0, tzinfo=UTC)
    created_event = SessionEvent.create(
        session_id=session_id,
        sequence=0,
        event_type=EventType.SESSION_CREATED,
        actor=EventActor.SYSTEM,
        payload={"title": "Replay Task"},
        created_at=created_at,
    )
    user_event = SessionEvent.create(
        session_id=session_id,
        sequence=1,
        event_type=EventType.USER_MESSAGE_RECEIVED,
        actor=EventActor.USER,
        payload={"content": "continue"},
        created_at=created_at,
    )

    store.append(created_event)
    store.append(user_event)

    assert store.list_for_session(session_id) == [created_event, user_event]


def test_sqlite_event_store_rejects_duplicate_sequence_for_same_session(
    tmp_path: Path,
) -> None:
    store = SQLiteEventStore(tmp_path / "events.db")
    session_id = new_session_id()
    created_at = datetime(2026, 6, 19, 23, 5, tzinfo=UTC)
    first_event = SessionEvent.create(
        session_id=session_id,
        sequence=0,
        event_type=EventType.SESSION_CREATED,
        actor=EventActor.SYSTEM,
        payload={"title": "Duplicate Task"},
        created_at=created_at,
    )
    conflicting_event = SessionEvent.create(
        session_id=session_id,
        sequence=0,
        event_type=EventType.USER_MESSAGE_RECEIVED,
        actor=EventActor.USER,
        payload={"content": "duplicate"},
        created_at=created_at,
    )

    store.append(first_event)

    with pytest.raises(ValueError, match="duplicate or conflicting session event"):
        store.append(conflicting_event)


def test_sqlite_event_store_supports_projection_rebuild(tmp_path: Path) -> None:
    store = SQLiteEventStore(tmp_path / "events.db")
    session_id = new_session_id()
    created_at = datetime(2026, 6, 19, 23, 10, tzinfo=UTC)
    store.append(
        SessionEvent.create(
            session_id=session_id,
            sequence=0,
            event_type=EventType.SESSION_CREATED,
            actor=EventActor.SYSTEM,
            payload={"title": "Projection Task"},
            created_at=created_at,
        )
    )
    store.append(
        SessionEvent.create(
            session_id=session_id,
            sequence=1,
            event_type=EventType.TASK_PREPARED,
            actor=EventActor.HARNESS,
            payload={"title": "Projection Task", "user_input": "continue"},
            created_at=created_at,
        )
    )
    store.append(
        SessionEvent.create(
            session_id=session_id,
            sequence=2,
            event_type=EventType.HARNESS_ATTEMPT_STARTED,
            actor=EventActor.HARNESS,
            payload={"attempt_number": 1},
            created_at=created_at,
        )
    )
    store.append(
        SessionEvent.create(
            session_id=session_id,
            sequence=3,
            event_type=EventType.SESSION_COMPLETED,
            actor=EventActor.HARNESS,
            payload={"summary": "done"},
            created_at=created_at,
        )
    )

    session = rebuild_session(store.list_for_session(session_id))

    assert session.session_id == session_id
    assert session.status.value == "completed"
    assert session.current_sequence == 3


def test_sqlite_event_store_returns_existing_event_for_idempotent_retry(
    tmp_path: Path,
) -> None:
    store = SQLiteEventStore(tmp_path / "events.db")
    session_id = new_session_id()
    created_at = datetime(2026, 6, 19, 23, 15, tzinfo=UTC)
    first_event = SessionEvent.create(
        session_id=session_id,
        sequence=0,
        event_type=EventType.TOOL_EXECUTION_COMPLETED,
        actor=EventActor.TOOL,
        payload={
            "attempt_number": 1,
            "tool_name": "tests.run",
            "status": "executed",
            "output": "ok",
            "metadata": {"exit_code": 0},
        },
        idempotency_key="tool-run-1",
        created_at=created_at,
    )
    retry_event = SessionEvent.create(
        session_id=session_id,
        sequence=1,
        event_type=EventType.TOOL_EXECUTION_COMPLETED,
        actor=EventActor.TOOL,
        payload={
            "attempt_number": 1,
            "tool_name": "tests.run",
            "status": "executed",
            "output": "ok",
            "metadata": {"exit_code": 0},
        },
        idempotency_key="tool-run-1",
        created_at=created_at,
    )

    stored_event = store.append(first_event)
    retried_event = store.append(retry_event)

    assert stored_event == first_event
    assert retried_event == first_event
    assert store.list_for_session(session_id) == [first_event]


def test_sqlite_event_store_rejects_idempotency_key_reuse_with_different_content(
    tmp_path: Path,
) -> None:
    store = SQLiteEventStore(tmp_path / "events.db")
    session_id = new_session_id()
    created_at = datetime(2026, 6, 19, 23, 16, tzinfo=UTC)
    first_event = SessionEvent.create(
        session_id=session_id,
        sequence=0,
        event_type=EventType.USER_MESSAGE_RECEIVED,
        actor=EventActor.USER,
        payload={"content": "first"},
        idempotency_key="message-1",
        created_at=created_at,
    )
    conflicting_event = SessionEvent.create(
        session_id=session_id,
        sequence=1,
        event_type=EventType.USER_MESSAGE_RECEIVED,
        actor=EventActor.USER,
        payload={"content": "different"},
        idempotency_key="message-1",
        created_at=created_at,
    )
    store.append(first_event)

    with pytest.raises(SessionEventIdempotencyConflictError):
        store.append(conflicting_event)

    assert store.list_for_session(session_id) == [first_event]


def test_sqlite_event_store_reads_only_events_after_sequence(tmp_path: Path) -> None:
    store = SQLiteEventStore(tmp_path / "events.db")
    session_id = new_session_id()
    created_at = datetime(2026, 6, 19, 23, 20, tzinfo=UTC)
    created_event = SessionEvent.create(
        session_id=session_id,
        sequence=0,
        event_type=EventType.SESSION_CREATED,
        actor=EventActor.SYSTEM,
        payload={"title": "Delta Task"},
        created_at=created_at,
    )
    prepared_event = SessionEvent.create(
        session_id=session_id,
        sequence=1,
        event_type=EventType.TASK_PREPARED,
        actor=EventActor.HARNESS,
        payload={"title": "Delta Task", "user_input": "continue"},
        created_at=created_at,
    )
    started_event = SessionEvent.create(
        session_id=session_id,
        sequence=2,
        event_type=EventType.HARNESS_ATTEMPT_STARTED,
        actor=EventActor.HARNESS,
        payload={"attempt_number": 1},
        created_at=created_at,
    )
    for event in (created_event, prepared_event, started_event):
        store.append(event)

    assert store.read_since(session_id, sequence=0) == [prepared_event, started_event]
    assert store.read_since(session_id, sequence=1) == [started_event]


@pytest.mark.parametrize(
    ("terminal_event_type", "expected_status"),
    (
        (EventType.APPROVAL_GRANTED, "running"),
        (EventType.APPROVAL_REJECTED, "failed"),
    ),
)
def test_projection_rebuild_and_projection_store_keep_proxy_approval_context_consistent(
    tmp_path: Path,
    terminal_event_type: EventType,
    expected_status: str,
) -> None:
    database_path = tmp_path / "events.db"
    event_store = SQLiteEventStore(database_path)
    projection_store = SQLiteProjectionStore(database_path)
    session_id = new_session_id()
    created_at = datetime(2026, 6, 29, 16, 0, tzinfo=UTC)
    events = [
        SessionEvent.create(
            session_id=session_id,
            sequence=0,
            event_type=EventType.SESSION_CREATED,
            actor=EventActor.SYSTEM,
            payload={"title": "Projection Consistency"},
            created_at=created_at,
        ),
        SessionEvent.create(
            session_id=session_id,
            sequence=1,
            event_type=EventType.TASK_PREPARED,
            actor=EventActor.HARNESS,
            payload={"title": "Projection Consistency", "user_input": "continue"},
            created_at=created_at,
        ),
        SessionEvent.create(
            session_id=session_id,
            sequence=2,
            event_type=EventType.HARNESS_ATTEMPT_STARTED,
            actor=EventActor.HARNESS,
            payload={"attempt_number": 1},
            created_at=created_at,
        ),
        SessionEvent.create(
            session_id=session_id,
            sequence=3,
            event_type=EventType.APPROVAL_REQUESTED,
            actor=EventActor.POLICY,
            payload={
                "attempt_number": 1,
                "tool_name": "mcp.github.create_pull_request",
                "reason": "proxy-routed external tool execution in test",
                "policy_profile": "full_access",
                "route": "mcp_proxy",
                "target": "github.create_pull_request",
                "network_profile": "mcp-proxy-only",
                "scope": [
                    "tool:mcp.github.create_pull_request",
                    "route:mcp_proxy",
                ],
            },
            created_at=created_at,
        ),
        SessionEvent.create(
            session_id=session_id,
            sequence=4,
            event_type=terminal_event_type,
            actor=EventActor.USER,
            payload={"operator": "alice", "reason": "done"},
            created_at=created_at,
        ),
    ]
    for event in events:
        event_store.append(event)

    rebuilt = rebuild_session(event_store.list_for_session(session_id))
    projection_store.save_session(rebuilt)
    loaded = projection_store.get_session(session_id)

    assert rebuilt.status.value == expected_status
    assert loaded is not None
    assert loaded.status.value == expected_status
    assert rebuilt.approval_context is None
    assert loaded.approval_context is None
