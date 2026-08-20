import base64
from datetime import UTC, datetime
from pathlib import Path
from uuid import UUID

from agent_core.application import SessionBootstrapCommand, SessionBootstrapService
from agent_core.application.session_projection import apply_event, rebuild_session
from agent_core.application.workspace_projection import rebuild_workspace
from agent_core.domain.events import EventActor, EventType, SessionEvent
from agent_core.domain.identifiers import SessionId
from agent_core.domain.sessions import SessionStatus
from agent_storage import (
    SQLiteEventStore,
    SQLiteProjectionStore,
    SQLiteSessionHandoffStore,
    SQLiteWorkspaceProjectionStore,
)
from zebra_agent_api import RouteAdapter, RouteRequest, create_app

NOW = datetime(2026, 7, 19, tzinfo=UTC)


def test_task_create_list_and_control_route_to_active_segment(tmp_path: Path) -> None:
    adapter = RouteAdapter(create_app(tmp_path / "tasks.sqlite"))
    created = adapter.handle(
        RouteRequest(
            "POST",
            "/tasks",
            body={"title": "Public task", "prompt": "Inspect", "workspace": str(tmp_path)},
        )
    )
    task_id = created.body["task_id"]
    cancelled = adapter.handle(RouteRequest("POST", f"/tasks/{task_id}/cancel", body={}))
    read = adapter.handle(RouteRequest("GET", f"/tasks/{task_id}"))

    assert created.status_code == 201
    assert created.body["session_id"] == task_id
    assert cancelled.body["session_id"] == task_id
    assert cancelled.body["status"] == "cancelled"
    assert read.body["status"] == "cancelled"


def test_task_context_control_routes_to_hidden_active_segment(tmp_path: Path) -> None:
    database = tmp_path / "tasks.sqlite"
    task_id = str(_seed_completed(database, tmp_path))
    adapter = RouteAdapter(create_app(database))
    appended = adapter.handle(
        RouteRequest("POST", f"/tasks/{task_id}/messages", body={"content": "Continue"})
    )

    compacted = adapter.handle(
        RouteRequest("POST", f"/tasks/{task_id}/context/compact", body={"focus": "continue"})
    )
    capsule_id = compacted.body["capsule"]["capsule_id"]
    recovered = adapter.handle(
        RouteRequest(
            "POST",
            f"/tasks/{task_id}/context/recover",
            body={"capsule_id": capsule_id},
        )
    )

    assert appended.status_code == 201
    assert appended.body["rolled_over"] is True
    assert compacted.status_code == 200
    assert recovered.body["status"] == "recovered"


def test_task_read_exposes_stable_final_message_identity(tmp_path: Path) -> None:
    database = tmp_path / "tasks.sqlite"
    task_id = str(
        _seed_completed(database, tmp_path, assistant_message="First round final")
    )
    adapter = RouteAdapter(create_app(database))

    read = adapter.handle(RouteRequest("GET", f"/tasks/{task_id}"))
    conversation = adapter.handle(
        RouteRequest("GET", f"/tasks/{task_id}/conversation")
    )
    final_items = [
        item
        for item in conversation.body["items"]
        if item["role"] == "final_response" and item["state"] == "completed"
    ]

    assert read.status_code == 200
    assert final_items
    assert read.body["final_message"] == {
        "message_id": final_items[-1]["item_id"],
        "cursor": final_items[-1]["cursor"],
    }


def test_final_message_identity_uses_the_latest_completed_final(
    tmp_path: Path,
) -> None:
    database = tmp_path / "tasks.sqlite"
    adapter = RouteAdapter(create_app(database))
    created = adapter.handle(
        RouteRequest(
            "POST",
            "/tasks",
            body={
                "title": "Two public turns",
                "prompt": "PRIVATE initial prompt",
                "public_content": "first user",
                "workspace": str(tmp_path),
            },
        )
    )
    task_id = str(created.body["task_id"])
    root_id = SessionId(UUID(task_id))
    root = SQLiteProjectionStore(database).get_session(root_id)
    assert root is not None
    event_store = SQLiteEventStore(database)
    root_events = (
        SessionEvent.create(
            session_id=root_id,
            sequence=root.current_sequence + 1,
            event_type=EventType.HARNESS_ATTEMPT_STARTED,
            actor=EventActor.HARNESS,
            payload={"attempt_number": 1},
            created_at=NOW,
        ),
        SessionEvent.create(
            session_id=root_id,
            sequence=root.current_sequence + 2,
            event_type=EventType.MODEL_RESPONSE_RECEIVED,
            actor=EventActor.HARNESS,
            payload={"assistant_message": "first final", "tool_call_count": 0},
            created_at=NOW,
        ),
        SessionEvent.create(
            session_id=root_id,
            sequence=root.current_sequence + 3,
            event_type=EventType.SESSION_COMPLETED,
            actor=EventActor.HARNESS,
            payload={"summary": "done"},
            created_at=NOW,
        ),
    )
    for event in root_events:
        event_store.append(event)
    for event in root_events:
        root = apply_event(root, event)
    SQLiteProjectionStore(database).save_session(root)

    appended = adapter.handle(
        RouteRequest(
            "POST",
            f"/tasks/{task_id}/messages",
            body={
                "content": "PRIVATE follow-up harness input",
                "public_content": "follow-up user",
            },
        )
    )
    segments = adapter.handle(
        RouteRequest("GET", f"/internal/tasks/{task_id}/segments")
    )
    child_id = SessionId(UUID(segments.body["segments"][-1]["session_id"]))
    child = SQLiteProjectionStore(database).get_session(child_id)
    assert child is not None
    event_store.append(
        SessionEvent.create(
            session_id=child_id,
            sequence=child.current_sequence + 1,
            event_type=EventType.MODEL_RESPONSE_RECEIVED,
            actor=EventActor.HARNESS,
            payload={"assistant_message": "follow-up final", "tool_call_count": 0},
            created_at=NOW,
        )
    )
    event_store.append(
        SessionEvent.create(
            session_id=child_id,
            sequence=child.current_sequence + 2,
            event_type=EventType.SESSION_COMPLETED,
            actor=EventActor.HARNESS,
            payload={"summary": "done"},
            created_at=NOW,
        )
    )

    read = adapter.handle(RouteRequest("GET", f"/tasks/{task_id}"))
    conversation = adapter.handle(
        RouteRequest("GET", f"/tasks/{task_id}/conversation")
    )
    final_items = [
        item
        for item in conversation.body["items"]
        if item["role"] == "final_response" and item["state"] == "completed"
    ]

    assert appended.status_code == 201
    assert len(final_items) == 2
    assert read.body["final_message"] == {
        "message_id": final_items[-1]["item_id"],
        "cursor": final_items[-1]["cursor"],
    }


def test_task_read_returns_artifact_output_contract_of_latest_final(
    tmp_path: Path,
) -> None:
    database = tmp_path / "tasks.sqlite"
    adapter = RouteAdapter(create_app(database))
    created = adapter.handle(
        RouteRequest(
            "POST",
            "/tasks",
            body={
                "title": "Typed output",
                "prompt": "PRIVATE prompt",
                "workspace": str(tmp_path),
            },
        )
    )
    task_id = str(created.body["task_id"])
    root_id = SessionId(UUID(task_id))
    root = SQLiteProjectionStore(database).get_session(root_id)
    assert root is not None
    event_store = SQLiteEventStore(database)
    events = (
        SessionEvent.create(
            session_id=root_id,
            sequence=root.current_sequence + 1,
            event_type=EventType.MODEL_RESPONSE_RECEIVED,
            actor=EventActor.HARNESS,
            payload={
                "assistant_message": "typed final",
                "tool_call_count": 0,
                "response_stage": "final",
                "output_contract": {
                    "contract_id": "finos.daily-trading-journal",
                    "contract_version": "1",
                    "structured_payload": {"business_date": "2026-08-04"},
                    "payload_digest": "sha256:" + "c" * 64,
                    "source_refs": ["broker:a"],
                },
            },
            created_at=NOW,
        ),
        SessionEvent.create(
            session_id=root_id,
            sequence=root.current_sequence + 2,
            event_type=EventType.SESSION_COMPLETED,
            actor=EventActor.HARNESS,
            payload={"summary": "done"},
            created_at=NOW,
        ),
    )
    for event in events:
        event_store.append(event)
    from agent_core.domain.sessions import SessionStatus

    SQLiteProjectionStore(database).save_session(
        root.model_copy(update={"status": SessionStatus.COMPLETED})
    )

    read = adapter.handle(RouteRequest("GET", f"/tasks/{task_id}"))
    assert read.status_code == 200
    assert read.body["artifact_output_contract"]["contract_id"] == (
        "finos.daily-trading-journal"
    )
    assert read.body["artifact_output_contract"]["source_refs"] == ["broker:a"]


def test_task_read_omits_output_contract_when_absent(tmp_path: Path) -> None:
    database = tmp_path / "tasks.sqlite"
    task_id = str(_seed_completed(database, tmp_path, assistant_message="plain"))
    adapter = RouteAdapter(create_app(database))
    read = adapter.handle(RouteRequest("GET", f"/tasks/{task_id}"))
    assert read.status_code == 200
    assert "artifact_output_contract" not in read.body


def _seed_follow_up_final(
    database: Path,
    adapter,
    task_id: str,
    *,
    payload: dict[str, object],
    assistant_message: str = "follow-up final",
) -> SessionId:
    """Roll the Task over to a terminal follow-up segment and seed its final."""
    appended = adapter.handle(
        RouteRequest(
            "POST",
            f"/tasks/{task_id}/messages",
            body={
                "content": "PRIVATE follow-up harness input",
                "public_content": "follow-up user",
            },
        )
    )
    assert appended.status_code == 201
    segments = adapter.handle(
        RouteRequest("GET", f"/internal/tasks/{task_id}/segments")
    )
    child_id = SessionId(UUID(segments.body["segments"][-1]["session_id"]))
    child = SQLiteProjectionStore(database).get_session(child_id)
    assert child is not None
    event_store = SQLiteEventStore(database)
    child_events = (
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
            payload={
                "assistant_message": assistant_message,
                "tool_call_count": 0,
                **payload,
            },
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
    for event in child_events:
        event_store.append(event)
    for event in child_events:
        child = apply_event(child, event)
    SQLiteProjectionStore(database).save_session(
        child.model_copy(update={"status": SessionStatus.COMPLETED})
    )
    return child_id


def test_task_read_never_binds_previous_round_contract_to_latest_final(
    tmp_path: Path,
) -> None:
    """Round 1 emits contract A; Round 2 is a plain final without a contract.
    The Task projection must not leak Round 1's contract onto Round 2."""
    database = tmp_path / "tasks.sqlite"
    adapter = RouteAdapter(create_app(database))
    created = adapter.handle(
        RouteRequest(
            "POST",
            "/tasks",
            body={
                "title": "Stable rounds",
                "prompt": "PRIVATE prompt",
                "workspace": str(tmp_path),
            },
        )
    )
    task_id = str(created.body["task_id"])
    root_id = SessionId(UUID(task_id))
    root = SQLiteProjectionStore(database).get_session(root_id)
    assert root is not None
    event_store = SQLiteEventStore(database)
    contract_a = {
        "contract_id": "finos.round-one",
        "contract_version": "1",
        "structured_payload": {"round": 1},
        "payload_digest": "sha256:" + "a" * 64,
        "source_refs": ["broker:a"],
    }
    root_events = (
        SessionEvent.create(
            session_id=root_id,
            sequence=root.current_sequence + 1,
            event_type=EventType.HARNESS_ATTEMPT_STARTED,
            actor=EventActor.HARNESS,
            payload={"attempt_number": 1},
            created_at=NOW,
        ),
        SessionEvent.create(
            session_id=root_id,
            sequence=root.current_sequence + 2,
            event_type=EventType.MODEL_RESPONSE_RECEIVED,
            actor=EventActor.HARNESS,
            payload={
                "assistant_message": "round one final",
                "tool_call_count": 0,
                "response_stage": "final",
                "output_contract": contract_a,
            },
            created_at=NOW,
        ),
        SessionEvent.create(
            session_id=root_id,
            sequence=root.current_sequence + 3,
            event_type=EventType.SESSION_COMPLETED,
            actor=EventActor.HARNESS,
            payload={"summary": "done"},
            created_at=NOW,
        ),
    )
    for event in root_events:
        event_store.append(event)
    for event in root_events:
        root = apply_event(root, event)
    SQLiteProjectionStore(database).save_session(
        root.model_copy(update={"status": SessionStatus.COMPLETED})
    )

    _seed_follow_up_final(
        database,
        adapter,
        task_id,
        payload={"response_stage": "final"},
    )
    read = adapter.handle(RouteRequest("GET", f"/tasks/{task_id}"))
    assert read.status_code == 200
    assert read.body["final_message"]["message_id"].startswith("final:")
    assert "artifact_output_contract" not in read.body


def test_task_read_binds_only_the_active_round_contract(tmp_path: Path) -> None:
    """Round 1 emits contract A; Round 2 emits contract B. The Task read must
    return B only, never A."""
    database = tmp_path / "tasks.sqlite"
    adapter = RouteAdapter(create_app(database))
    created = adapter.handle(
        RouteRequest(
            "POST",
            "/tasks",
            body={
                "title": "Stable rounds",
                "prompt": "PRIVATE prompt",
                "workspace": str(tmp_path),
            },
        )
    )
    task_id = str(created.body["task_id"])
    root_id = SessionId(UUID(task_id))
    root = SQLiteProjectionStore(database).get_session(root_id)
    assert root is not None
    event_store = SQLiteEventStore(database)
    contract_a = {
        "contract_id": "finos.round-one",
        "contract_version": "1",
        "structured_payload": {"round": 1},
        "payload_digest": "sha256:" + "a" * 64,
        "source_refs": ["broker:a"],
    }
    contract_b = {
        "contract_id": "finos.round-two",
        "contract_version": "1",
        "structured_payload": {"round": 2},
        "payload_digest": "sha256:" + "b" * 64,
        "source_refs": ["broker:b"],
    }
    root_events = (
        SessionEvent.create(
            session_id=root_id,
            sequence=root.current_sequence + 1,
            event_type=EventType.HARNESS_ATTEMPT_STARTED,
            actor=EventActor.HARNESS,
            payload={"attempt_number": 1},
            created_at=NOW,
        ),
        SessionEvent.create(
            session_id=root_id,
            sequence=root.current_sequence + 2,
            event_type=EventType.MODEL_RESPONSE_RECEIVED,
            actor=EventActor.HARNESS,
            payload={
                "assistant_message": "round one final",
                "tool_call_count": 0,
                "response_stage": "final",
                "output_contract": contract_a,
            },
            created_at=NOW,
        ),
        SessionEvent.create(
            session_id=root_id,
            sequence=root.current_sequence + 3,
            event_type=EventType.SESSION_COMPLETED,
            actor=EventActor.HARNESS,
            payload={"summary": "done"},
            created_at=NOW,
        ),
    )
    for event in root_events:
        event_store.append(event)
    for event in root_events:
        root = apply_event(root, event)
    SQLiteProjectionStore(database).save_session(
        root.model_copy(update={"status": SessionStatus.COMPLETED})
    )

    _seed_follow_up_final(
        database,
        adapter,
        task_id,
        payload={"response_stage": "final", "output_contract": contract_b},
    )
    read = adapter.handle(RouteRequest("GET", f"/tasks/{task_id}"))
    assert read.status_code == 200
    assert read.body["artifact_output_contract"]["contract_id"] == (
        "finos.round-two"
    )
    assert read.body["artifact_output_contract"]["source_refs"] == ["broker:b"]


def test_task_routes_keep_one_identity_across_automatic_follow_up_rollover(
    tmp_path: Path,
) -> None:
    database = tmp_path / "tasks.sqlite"
    task_id = str(
        _seed_completed(
            database,
            tmp_path,
            assistant_message="长江电力今日上涨。需要继续分析资金流向吗？",
        )
    )
    adapter = RouteAdapter(create_app(database))

    before = adapter.handle(RouteRequest("GET", f"/tasks/{task_id}"))
    appended = adapter.handle(
        RouteRequest(
            "POST",
            f"/tasks/{task_id}/messages",
            body={
                "content": "Continue without showing an internal thread",
                "attachments": [
                    {
                        "file_name": "context.txt",
                        "media_type": "text/plain",
                        "content_base64": base64.b64encode(b"durable context").decode(),
                    }
                ],
            },
            headers={"Idempotency-Key": "follow-up-1"},
        )
    )
    replayed = adapter.handle(
        RouteRequest(
            "POST",
            f"/tasks/{task_id}/messages",
            body={
                "content": "Continue without showing an internal thread",
                "attachments": [
                    {
                        "file_name": "context.txt",
                        "media_type": "text/plain",
                        "content_base64": base64.b64encode(b"durable context").decode(),
                    }
                ],
            },
            headers={"Idempotency-Key": "follow-up-1"},
        )
    )
    after = adapter.handle(RouteRequest("GET", f"/tasks/{task_id}"))
    listing = adapter.handle(RouteRequest("GET", "/tasks", query={"limit": "10"}))
    stream = adapter.handle(RouteRequest("GET", f"/tasks/{task_id}/stream"))
    internal = adapter.handle(RouteRequest("GET", f"/internal/tasks/{task_id}/segments"))

    assert before.status_code == 200
    assert appended.status_code == 201
    assert appended.body["rolled_over"] is True
    assert appended.body["session_id"] == task_id
    assert appended.body["attachments"][0]["file_name"] == "context.txt"
    assert replayed.body == appended.body
    assert after.body["session_id"] == task_id
    assert after.body["task_id"] == task_id
    assert after.body["status"] == "ready"
    assert listing.body["count"] == 1
    assert len(internal.body["segments"]) == 2
    assert internal.body["segments"][1]["rollover_reason"] == "terminal_follow_up"
    child_id = SessionId(UUID(internal.body["segments"][1]["session_id"]))
    lineage = SQLiteSessionHandoffStore(database).get_lineage(child_id)
    handoff_id = lineage[-1].inbound_handoff_id
    assert handoff_id is not None
    envelope = SQLiteSessionHandoffStore(database).get_envelope(handoff_id)
    assert envelope is not None
    assert envelope.objective == "Start"
    assert envelope.completed_work == (
        "Prior user request: Start",
        "Prior assistant response: 长江电力今日上涨。需要继续分析资金流向吗？",
    )
    assert "handoff_id" not in str(stream.body)
    assert (
        sum(
            event["payload"].get("content") == "Continue without showing an internal thread"
            for event in stream.body["events"]
        )
        == 1
    )


def test_internal_rollover_controller_pauses_unsafe_boundary(tmp_path: Path) -> None:
    database = tmp_path / "tasks.sqlite"
    task_id = str(_seed_completed(database, tmp_path))
    response = RouteAdapter(create_app(database)).handle(
        RouteRequest(
            "POST",
            f"/internal/tasks/{task_id}/segments/rollover",
            body={"signals": {"agent_rollover_hint": True, "pending_approval": True}},
        )
    )

    assert response.body == {
        "task_id": task_id,
        "decision": "pause_for_approval_or_clarification",
    }


def test_cancelled_task_follow_up_recovers_behind_the_same_task_id(tmp_path: Path) -> None:
    database = tmp_path / "tasks.sqlite"
    task_id = str(_seed_completed(database, tmp_path, EventType.SESSION_CANCELLED))
    adapter = RouteAdapter(create_app(database))

    response = adapter.handle(
        RouteRequest(
            "POST",
            f"/tasks/{task_id}/messages",
            body={"content": "Start the next request after cancellation"},
        )
    )
    segments = adapter.handle(RouteRequest("GET", f"/internal/tasks/{task_id}/segments"))

    assert response.status_code == 201
    assert response.body["session_id"] == task_id
    assert response.body["rolled_over"] is True
    assert len(segments.body["segments"]) == 2
    assert segments.body["segments"][1]["rollover_reason"] == "recovery"


def test_internal_segment_approval_projects_the_stable_task_id(tmp_path: Path) -> None:
    database = tmp_path / "tasks.sqlite"
    task_id = str(_seed_completed(database, tmp_path, EventType.SESSION_CANCELLED))
    adapter = RouteAdapter(create_app(database))
    adapter.handle(
        RouteRequest(
            "POST",
            f"/tasks/{task_id}/messages",
            body={"content": "Continue into approval"},
        )
    )
    segments = adapter.handle(RouteRequest("GET", f"/internal/tasks/{task_id}/segments"))
    internal_id = segments.body["segments"][1]["session_id"]
    projection_store = SQLiteProjectionStore(database)
    internal = projection_store.get_session(SessionId(UUID(internal_id)))

    assert internal is not None
    projection_store.save_session(
        internal.model_copy(update={"status": SessionStatus.WAITING_APPROVAL})
    )
    approval = adapter.handle(RouteRequest("GET", "/approvals")).body["approvals"][0]

    assert approval["approval_id"] == internal_id
    assert approval["session_id"] == task_id


def _seed_completed(
    database: Path,
    workspace: Path,
    terminal_event: EventType = EventType.SESSION_COMPLETED,
    *,
    assistant_message: str = "Done",
):
    bootstrap = SessionBootstrapService().build(
        SessionBootstrapCommand(
            title="Stable task",
            user_input="Start",
            workspace_root=workspace.resolve(),
            created_at=NOW,
        )
    )
    events = [
        *bootstrap.events,
        SessionEvent.create(
            session_id=bootstrap.session.session_id,
            sequence=3,
            event_type=EventType.HARNESS_ATTEMPT_STARTED,
            actor=EventActor.HARNESS,
            payload={"attempt_number": 1},
            created_at=NOW,
        ),
        SessionEvent.create(
            session_id=bootstrap.session.session_id,
            sequence=4,
            event_type=EventType.MODEL_RESPONSE_RECEIVED,
            actor=EventActor.HARNESS,
            payload={"assistant_message": assistant_message},
            created_at=NOW,
        ),
        SessionEvent.create(
            session_id=bootstrap.session.session_id,
            sequence=5,
            event_type=terminal_event,
            actor=EventActor.HARNESS,
            payload={"summary": "done", "assistant_message": assistant_message},
            created_at=NOW,
        ),
    ]
    store = SQLiteEventStore(database)
    for event in events:
        store.append(event)
    SQLiteProjectionStore(database).save_session(rebuild_session(events))
    SQLiteWorkspaceProjectionStore(database).save_workspace(rebuild_workspace(events))
    return bootstrap.session.session_id
