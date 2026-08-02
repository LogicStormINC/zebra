import json
from datetime import UTC, datetime
from hashlib import sha256
from pathlib import Path
from uuid import UUID

from fastapi.testclient import TestClient

from agent_core.application import SessionBootstrapCommand, SessionBootstrapService
from agent_core.application.session_projection import apply_event, rebuild_session
from agent_core.application.workspace_projection import rebuild_workspace
from agent_core.domain.context_capsule import (
    ContextCapsule,
    ContextCapsuleValidationContext,
    ContextSourceEventRange,
    PendingToolState,
)
from agent_core.domain.events import EventActor, EventType, SessionEvent
from agent_core.domain.identifiers import SessionId
from agent_storage import (
    SQLiteAgentTaskStore,
    SQLiteContextLifecycleStore,
    SQLiteEventStore,
    SQLiteProjectionStore,
    SQLiteWorkspaceProjectionStore,
)
from zebra_agent_api.http import create_http_app
from zebra_agent_config import load_settings

NOW = datetime(2026, 8, 2, tzinfo=UTC)


def test_http_terminal_follow_up_reconciles_stale_pending_capsule(tmp_path: Path) -> None:
    database = tmp_path / "terminal-follow-up.sqlite"
    task_id = _seed_stale_terminal_task(database, tmp_path)
    client = TestClient(
        create_http_app(
            database,
            settings=load_settings({"ZEBRA_SESSION_HANDOFF_ENABLED": "true"}),
        )
    )

    response = client.post(
        f"/tasks/{task_id}/messages",
        json={"content": "Continue after the completed tool.", "public_content": "second user"},
        headers={"Idempotency-Key": "terminal-follow-up"},
    )

    assert response.status_code == 201, response.text
    assert response.json()["task_id"] == task_id
    assert response.json()["rolled_over"] is True

    segments = client.get(f"/internal/tasks/{task_id}/segments").json()["segments"]
    assert len(segments) == 2
    child_id = SessionId(UUID(segments[-1]["session_id"]))
    child_events = SQLiteEventStore(database).list_for_session(child_id)
    prepared = next(event for event in child_events if event.event_type is EventType.TASK_PREPARED)
    assert prepared.payload["model_id"] == "non-default-model"

    child = SQLiteProjectionStore(database).get_session(child_id)
    assert child is not None
    event_store = SQLiteEventStore(database)
    final_events = (
        SessionEvent.create(
            session_id=child_id,
            sequence=child.current_sequence + 1,
            event_type=EventType.MODEL_RESPONSE_RECEIVED,
            actor=EventActor.HARNESS,
            payload={"assistant_message": "second final", "tool_call_count": 0},
            created_at=NOW,
        ),
        SessionEvent.create(
            session_id=child_id,
            sequence=child.current_sequence + 2,
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

    conversation = client.get(f"/tasks/{task_id}/conversation").json()
    assert [
        (item["role"], item["content"])
        for item in conversation["items"]
        if item["role"] in {"user_message", "final_response"}
    ] == [
        ("user_message", "first user"),
        ("final_response", "first final"),
        ("user_message", "second user"),
        ("final_response", "second final"),
    ]


def _seed_stale_terminal_task(database: Path, workspace: Path) -> str:
    bootstrap = SessionBootstrapService().build(
        SessionBootstrapCommand(
            title="Stale capsule task",
            user_input="first request",
            public_content="first user",
            workspace_root=workspace.resolve(),
            model_id="non-default-model",
            created_at=NOW,
        )
    )
    prefix = [
        *bootstrap.events,
        _event(
            bootstrap.session.session_id,
            3,
            EventType.HARNESS_ATTEMPT_STARTED,
            EventActor.HARNESS,
            {"attempt_number": 1},
        ),
        _event(
            bootstrap.session.session_id,
            4,
            EventType.APPROVAL_REQUESTED,
            EventActor.POLICY,
            {
                "attempt_number": 1,
                "tool_name": "files.read",
                "tool_call_id": "call-stale",
                "reason": "approval required",
            },
        ),
    ]
    event_store = SQLiteEventStore(database)
    for event in prefix:
        event_store.append(event)
    SQLiteProjectionStore(database).save_session(rebuild_session(prefix))
    SQLiteWorkspaceProjectionStore(database).save_workspace(rebuild_workspace(prefix))

    capsule = ContextCapsule(
        capsule_id="stale-terminal-capsule",
        objective="Preserve the first request evidence.",
        protected_user_constraints=("preserve evidence",),
        pending_tools=(
            PendingToolState(call_id="call-stale", name="files.read"),
        ),
        approvals_and_policy_state=("approval_requested:approval required",),
        immediate_next="Resume the approved read.",
        source_event_range=ContextSourceEventRange(start_sequence=0, end_sequence=4),
        source_hash=_event_hash(prefix),
        confidence=1.0,
        created_at=NOW,
    )
    SQLiteContextLifecycleStore(database).persist_capsule_and_advance(
        session_id=bootstrap.session.session_id,
        capsule=capsule,
        validation_context=ContextCapsuleValidationContext(
            expected_source_hash=capsule.source_hash,
            expected_source_event_range=capsule.source_event_range,
            unresolved_tool_call_ids=frozenset({"call-stale"}),
            protected_user_constraints=frozenset(capsule.protected_user_constraints),
            approval_and_policy_state=frozenset(capsule.approvals_and_policy_state),
        ),
        sequence=5,
        expected_active_capsule_id=None,
        created_at=NOW,
    )
    tail = [
        _event(
            bootstrap.session.session_id,
            6,
            EventType.APPROVAL_GRANTED,
            EventActor.USER,
            {"tool_call_id": "call-stale"},
        ),
        _event(
            bootstrap.session.session_id,
            7,
            EventType.TOOL_EXECUTION_STARTED,
            EventActor.HARNESS,
            {"attempt_number": 1, "tool_name": "files.read", "tool_call_id": "call-stale"},
        ),
        _event(
            bootstrap.session.session_id,
            8,
            EventType.TOOL_EXECUTION_COMPLETED,
            EventActor.TOOL,
            {
                "attempt_number": 1,
                "tool_name": "files.read",
                "tool_call_id": "call-stale",
                "status": "executed",
                "output": "durable result",
                "metadata": {},
            },
        ),
        _event(
            bootstrap.session.session_id,
            9,
            EventType.MODEL_RESPONSE_RECEIVED,
            EventActor.HARNESS,
            {"assistant_message": "first final", "tool_call_count": 1},
        ),
        _event(
            bootstrap.session.session_id,
            10,
            EventType.SESSION_COMPLETED,
            EventActor.HARNESS,
            {"summary": "done"},
        ),
    ]
    for event in tail:
        event_store.append(event)
    all_events = [*prefix, *event_store.list_for_session(bootstrap.session.session_id)[5:6], *tail]
    SQLiteProjectionStore(database).save_session(rebuild_session(all_events))
    SQLiteAgentTaskStore(database).ensure_for_session(bootstrap.session.session_id)
    return str(bootstrap.session.session_id)


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


def _event_hash(events: list[SessionEvent]) -> str:
    encoded = json.dumps(
        [event.model_dump(mode="json") for event in events],
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    ).encode()
    return sha256(encoded).hexdigest()
