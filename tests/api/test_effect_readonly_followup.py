from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from uuid import UUID

from agent_core.application import SessionBootstrapCommand, SessionBootstrapService
from agent_core.application.session_projection import apply_event, rebuild_session
from agent_core.application.workspace_projection import rebuild_workspace
from agent_core.domain.events import EventActor, EventType, SessionEvent
from agent_core.domain.identifiers import SessionId
from agent_core.domain.session_handoff import EffectIdentity
from agent_storage import (
    SQLiteAgentTaskStore,
    SQLiteEffectLedger,
    SQLiteEventStore,
    SQLiteProjectionStore,
    SQLiteWorkspaceProjectionStore,
)
from fastapi.testclient import TestClient
from zebra_agent_api.http import create_http_app
from zebra_agent_config import load_settings

NOW = datetime(2026, 8, 2, tzinfo=UTC)


def test_terminal_follow_up_after_failed_read_only_tool_creates_child(
    tmp_path: Path,
) -> None:
    database = tmp_path / "follow-up-read-only.sqlite"
    task_id = _seed_completed_task_with_failed_read_only_tool(database, tmp_path)
    client = _client(database)

    response = client.post(
        f"/tasks/{task_id}/messages",
        json={"content": "Continue after the failed read.", "public_content": "second user"},
        headers={"Idempotency-Key": "follow-up-read-only"},
    )

    assert response.status_code == 201, response.text
    assert response.json()["rolled_over"] is True
    segments = client.get(f"/internal/tasks/{task_id}/segments").json()["segments"]
    assert len(segments) == 2


def test_terminal_follow_up_rejects_uncertain_effect_without_child(tmp_path: Path) -> None:
    database = tmp_path / "follow-up-uncertain.sqlite"
    task_id = _seed_completed_task_with_failed_read_only_tool(database, tmp_path)
    _poison_ledger_with_uncertain(database, SessionId(UUID(task_id)))
    client = _client(database)

    response = client.post(
        f"/tasks/{task_id}/messages",
        json={"content": "Continue after the uncertain effect."},
        headers={"Idempotency-Key": "follow-up-uncertain"},
    )

    assert response.status_code == 409, response.text
    assert response.json()["status"] == "handoff_rejected"
    assert response.json()["reason"] == "handoff_source_not_quiescent"
    segments = client.get(f"/internal/tasks/{task_id}/segments").json()["segments"]
    assert len(segments) == 1


def test_terminal_follow_up_across_segments_after_read_only_failure(
    tmp_path: Path,
) -> None:
    database = tmp_path / "follow-up-multi-segment.sqlite"
    task_id = _seed_completed_task_with_failed_read_only_tool(database, tmp_path)
    client = _client(database)

    first = client.post(
        f"/tasks/{task_id}/messages",
        json={"content": "Second round."},
        headers={"Idempotency-Key": "follow-up-round-2"},
    )
    assert first.status_code == 201, first.text
    segments = client.get(f"/internal/tasks/{task_id}/segments").json()["segments"]
    assert len(segments) == 2

    child_id = SessionId(UUID(segments[-1]["session_id"]))
    event_store = SQLiteEventStore(database)
    child = SQLiteProjectionStore(database).get_session(child_id)
    assert child is not None
    final_events = (
        SessionEvent.create(
            session_id=child_id,
            sequence=child.current_sequence + 1,
            event_type=EventType.HARNESS_ATTEMPT_STARTED,
            actor=EventActor.HARNESS,
            payload={"attempt_number": 1},
            created_at=NOW,
        ),
        SessionEvent.create(
            session_id=child_id,
            sequence=child.current_sequence + 2,
            event_type=EventType.MODEL_RESPONSE_RECEIVED,
            actor=EventActor.HARNESS,
            payload={"assistant_message": "second final", "tool_call_count": 0},
            created_at=NOW,
        ),
        SessionEvent.create(
            session_id=child_id,
            sequence=child.current_sequence + 3,
            event_type=EventType.SESSION_COMPLETED,
            actor=EventActor.HARNESS,
            payload={"summary": "done"},
            created_at=NOW,
        ),
    )
    for event in final_events:
        event_store.append(event)
        child = apply_event(child, event)
    SQLiteProjectionStore(database).save_session(child)

    second = client.post(
        f"/tasks/{task_id}/messages",
        json={"content": "Third round."},
        headers={"Idempotency-Key": "follow-up-round-3"},
    )
    assert second.status_code == 201, second.text
    segments = client.get(f"/internal/tasks/{task_id}/segments").json()["segments"]
    assert len(segments) == 3


def _client(database: Path) -> TestClient:
    return TestClient(
        create_http_app(
            database,
            settings=load_settings({"ZEBRA_SESSION_HANDOFF_ENABLED": "true"}),
        )
    )


def _seed_completed_task_with_failed_read_only_tool(
    database: Path,
    workspace: Path,
) -> str:
    bootstrap = SessionBootstrapService().build(
        SessionBootstrapCommand(
            title="Read-only failure task",
            user_input="first request",
            public_content="first user",
            workspace_root=workspace.resolve(),
            model_id="non-default-model",
            created_at=NOW,
        )
    )
    session_id = bootstrap.session.session_id
    event_store = SQLiteEventStore(database)
    prefix = [
        *bootstrap.events,
        _event(
            session_id,
            3,
            EventType.HARNESS_ATTEMPT_STARTED,
            EventActor.HARNESS,
            {"attempt_number": 1},
        ),
    ]
    tail = (
        _event(
            session_id,
            4,
            EventType.TOOL_EXECUTION_STARTED,
            EventActor.HARNESS,
            {
                "attempt_number": 1,
                "tool_name": "finos.notes.list",
                "tool_call_id": "notes-list-call",
            },
        ),
        _event(
            session_id,
            5,
            EventType.TOOL_EXECUTION_COMPLETED,
            EventActor.TOOL,
            {
                "attempt_number": 1,
                "tool_name": "finos.notes.list",
                "tool_call_id": "notes-list-call",
                "status": "failed",
                "output": "",
                "metadata": {"reason": "finos_journal_provider_error"},
            },
        ),
        _event(
            session_id,
            6,
            EventType.MODEL_RESPONSE_RECEIVED,
            EventActor.HARNESS,
            {"assistant_message": "first final", "tool_call_count": 1, "response_stage": "final"},
        ),
        _event(
            session_id,
            7,
            EventType.SESSION_COMPLETED,
            EventActor.HARNESS,
            {"summary": "done"},
        ),
    )
    for event in (*prefix, *tail):
        event_store.append(event)
    SQLiteProjectionStore(database).save_session(rebuild_session([*prefix, *tail]))
    SQLiteWorkspaceProjectionStore(database).save_workspace(
        rebuild_workspace([*prefix, *tail])
    )
    SQLiteAgentTaskStore(database).ensure_for_session(session_id)
    return str(session_id)


def _poison_ledger_with_uncertain(database: Path, root_session_id: SessionId) -> None:
    ledger = SQLiteEffectLedger(database)
    reservation = ledger.reserve(root_session_id, _effect_identity())
    ledger.mark_executing(reservation)
    ledger.mark_uncertain(reservation)


def _effect_identity() -> EffectIdentity:
    return EffectIdentity(
        authority_scope_hash="authority",
        tool_name="command.run",
        operation_kind="command.run",
        target_hash="target",
        canonical_effect_hash="effect",
    )


def _event(
    session_id: SessionId,
    sequence: int,
    event_type: EventType,
    actor: EventActor,
    payload: dict[str, object],
) -> SessionEvent:
    return SessionEvent.create(
        session_id=session_id,
        sequence=sequence,
        event_type=event_type,
        actor=actor,
        payload=payload,
        created_at=NOW,
    )
