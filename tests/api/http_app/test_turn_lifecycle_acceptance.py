"""ADR-026 acceptance matrix: multi-turn continuity, admission, crash heal."""

from datetime import UTC, datetime
from pathlib import Path
from uuid import UUID

import pytest
import zebra_agent_worker.execution as worker_execution_module
from agent_core.application.mock_model import ScriptedModelGateway, ScriptedModelResponse
from agent_core.domain.identifiers import SessionId, new_message_id
from agent_core.domain.messages import MessageRole, SessionMessage
from agent_core.domain.modeling import ModelCompletion
from fastapi.testclient import TestClient
from http_app_support import (
    _counting_gateway,
    _create_conversation_task,
    _run_turn,
    _settings,
)
from zebra_agent_api import create_http_app
from zebra_agent_config import ZebraAgentSettings


def _gateway_for(*replies: str):
    def factory(_settings: ZebraAgentSettings) -> ScriptedModelGateway:
        return ScriptedModelGateway(
            responses=tuple(
                ScriptedModelResponse(
                    completion=ModelCompletion(
                        assistant_message=SessionMessage(
                            message_id=new_message_id(),
                            role=MessageRole.ASSISTANT,
                            content=reply,
                            created_at=datetime(2026, 8, 24, 12, 0, tzinfo=UTC),
                        )
                    )
                )
                for reply in replies
            )
        )

    return factory



def test_conversation_task_keeps_one_segment_across_turns(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(
        worker_execution_module,
        "build_model_gateway",
        _gateway_for("Turn one done.", "Turn two done."),
    )
    client = TestClient(create_http_app(tmp_path / "turns.sqlite", settings=_settings(None)))
    task_id = _create_conversation_task(client, workspace_root=tmp_path)

    first = _run_turn(client, task_id)
    assert first["status"] == "awaiting_turn"

    detail = client.get(f"/tasks/{task_id}").json()
    assert detail["task_status"] == "open"
    assert detail["current_turn_status"] == "completed"
    assert detail["interaction_mode"] == "conversation"
    assert detail["turn_id"]
    original_segment = detail["active_segment_id"]

    follow_up = client.post(f"/tasks/{task_id}/messages", json={"content": "What is the codeword?"})
    assert follow_up.status_code == 201
    assert follow_up.json().get("rolled_over") is not True

    second = _run_turn(client, task_id)
    assert second["status"] == "awaiting_turn"

    detail = client.get(f"/tasks/{task_id}").json()
    assert detail["active_segment_id"] == original_segment
    assert detail["task_status"] == "open"

    segments = client.get(f"/internal/tasks/{task_id}/segments").json()
    segment_ids = [segment["session_id"] for segment in segments["segments"]]
    assert segment_ids == [original_segment]

    from agent_storage import SQLiteEventStore

    events = SQLiteEventStore(tmp_path / "turns.sqlite").list_for_session(
        SessionId(UUID(original_segment))
    )
    turn_closes = [event for event in events if event.event_type.value == "turn_completed"]
    assert len(turn_closes) == 2
    assert all(event.payload["closes_segment"] is False for event in turn_closes)
    assert not any(event.event_type.value == "session_completed" for event in events)
    assert len({event.payload["turn_id"] for event in turn_closes}) == 2

def test_one_shot_task_still_writes_session_completed_for_legacy_consumers(
    tmp_path: Path, monkeypatch
) -> None:
    monkeypatch.setattr(
        worker_execution_module,
        "build_model_gateway",
        _gateway_for("One shot answer."),
    )
    client = TestClient(create_http_app(tmp_path / "oneshot.sqlite", settings=_settings(None)))
    response = client.post(
        "/tasks",
        json={"prompt": "Summarize once.", "title": "One-shot acceptance"},
    )
    assert response.status_code == 201
    task_id = str(response.json()["task_id"])

    executed = _run_turn(client, task_id)
    assert executed["status"] == "completed"

    detail = client.get(f"/tasks/{task_id}").json()
    assert detail["task_status"] == "completed"
    assert detail["interaction_mode"] == "one_shot"

def test_second_message_during_running_turn_is_rejected(tmp_path: Path, monkeypatch) -> None:
    from agent_core.application import (
        SessionMessageAppendCommand,
        SessionMessageAppendService,
    )
    from agent_core.domain.sessions import Session, SessionStatus

    running = Session.create(title="busy").model_copy(update={"status": SessionStatus.RUNNING})
    with pytest.raises(ValueError, match="turn_in_progress"):
        SessionMessageAppendService().build_event(
            session=running,
            next_sequence=1,
            command=SessionMessageAppendCommand(content="second while running"),
        )

def test_task_message_idempotency_replays_same_turn_and_conflicts_on_drift(
    tmp_path: Path, monkeypatch
) -> None:
    monkeypatch.setattr(
        worker_execution_module,
        "build_model_gateway",
        _gateway_for("Turn one done."),
    )
    client = TestClient(create_http_app(tmp_path / "idem.sqlite", settings=_settings(None)))
    task_id = _create_conversation_task(client, workspace_root=tmp_path)
    _run_turn(client, task_id)

    headers = {"Idempotency-Key": "acceptance-key-1"}
    first = client.post(
        f"/tasks/{task_id}/messages",
        json={"content": "First follow-up."},
        headers=headers,
    )
    assert first.status_code == 201

    replay = client.post(
        f"/tasks/{task_id}/messages",
        json={"content": "First follow-up."},
        headers=headers,
    )
    assert replay.status_code == 201
    assert replay.json()["sequence"] == first.json()["sequence"]

    drifted = client.post(
        f"/tasks/{task_id}/messages",
        json={"content": "Different content, same key."},
        headers=headers,
    )
    assert drifted.status_code == 409
    assert drifted.json()["status"] == "idempotency_conflict"

def test_ag_ui_run_finishes_per_turn_and_restarts_on_the_next_message() -> None:
    from ag_ui.core import RunErrorEvent, RunFinishedEvent, RunStartedEvent
    from agent_core.application import SessionBootstrapCommand, SessionBootstrapService
    from agent_core.domain.events import EventActor, EventType, SessionEvent
    from agent_core.domain.turns import derive_turn_id
    from agent_integrations.ag_ui.contracts import AgUiRunIdentity
    from agent_integrations.ag_ui.projection import AgUiProjector

    bootstrap = SessionBootstrapService().build(
        SessionBootstrapCommand(
            title="AG-UI turns",
            user_input="Turn one.",
            workspace_root=Path("/tmp/agui"),
        )
    )
    events = list(bootstrap.events)
    second_turn = str(derive_turn_id(events[0].session_id, 1))

    def append(event_type: EventType, payload: dict[str, object], actor: EventActor) -> None:
        events.append(
            SessionEvent.create(
                session_id=events[0].session_id,
                sequence=events[-1].sequence + 1,
                event_type=event_type,
                actor=actor,
                payload=payload,
            )
        )

    append(EventType.HARNESS_ATTEMPT_STARTED, {"attempt_number": 1}, EventActor.HARNESS)
    append(
        EventType.MODEL_RESPONSE_RECEIVED,
        {"assistant_message": "First answer.", "model_call_id": "m1"},
        EventActor.HARNESS,
    )
    append(
        EventType.TURN_COMPLETED,
        {
            "turn_id": str(derive_turn_id(events[0].session_id, 0)),
            "turn_index": 0,
            "summary": "First answer.",
            "closes_segment": False,
        },
        EventActor.HARNESS,
    )
    append(
        EventType.USER_MESSAGE_RECEIVED,
        {"content": "Turn two.", "turn_id": second_turn, "turn_index": 1, "origin": "human"},
        EventActor.USER,
    )
    append(EventType.HARNESS_ATTEMPT_STARTED, {"attempt_number": 1}, EventActor.HARNESS)
    append(
        EventType.MODEL_RESPONSE_RECEIVED,
        {"assistant_message": "Second answer.", "model_call_id": "m2"},
        EventActor.HARNESS,
    )
    append(
        EventType.TURN_FAILED,
        {
            "turn_id": second_turn,
            "turn_index": 1,
            "reason": "provider failed",
            "closes_segment": True,
        },
        EventActor.HARNESS,
    )
    append(
        EventType.SESSION_FAILED,
        {"attempt_number": 1, "summary": "provider failed"},
        EventActor.HARNESS,
    )

    identity = AgUiRunIdentity(
        session_id=events[0].session_id, thread_id="task-1", run_id="segment-1"
    )
    projection = AgUiProjector().project(events, identity)
    kinds = [type(event) for event in projection.events]

    assert kinds.count(RunStartedEvent) == 2  # segment start + second turn
    assert kinds.count(RunFinishedEvent) == 1  # first turn success
    assert kinds.count(RunErrorEvent) == 1  # second turn failure, no duplicate

def test_awaiting_turn_resume_is_rejected_without_a_new_message(
    tmp_path: Path, monkeypatch
) -> None:
    counter: dict[str, int] = {"calls": 0}
    _counting_gateway(monkeypatch, counter, "Turn one done.")
    client = TestClient(create_http_app(tmp_path / "noresume.sqlite", settings=_settings(None)))
    task_id = _create_conversation_task(client, workspace_root=tmp_path)
    assert _run_turn(client, task_id)["status"] == "awaiting_turn"

    response = client.post(f"/tasks/{task_id}/resume", json={})

    assert response.status_code == 409
    assert response.json()["reason"] == "awaiting_next_turn_message"
    assert counter["calls"] == 1  # no second model invocation

def test_message_on_ready_bootstrap_with_open_turn_is_rejected(
    tmp_path: Path, monkeypatch
) -> None:
    _counting_gateway(monkeypatch, {"calls": 0}, "unused")
    client = TestClient(create_http_app(tmp_path / "open.sqlite", settings=_settings(None)))
    task_id = _create_conversation_task(client, workspace_root=tmp_path)

    early = client.post(f"/tasks/{task_id}/messages", json={"content": "Before first run."})

    assert early.status_code == 409
    assert early.json()["reason"] == "turn_in_progress"

def test_awaiting_turn_task_can_be_cancelled_and_suspended(
    tmp_path: Path, monkeypatch
) -> None:
    counter: dict[str, int] = {"calls": 0}
    _counting_gateway(monkeypatch, counter, "Turn one done.")
    client = TestClient(create_http_app(tmp_path / "control.sqlite", settings=_settings(None)))
    task_id = _create_conversation_task(client, workspace_root=tmp_path)
    assert _run_turn(client, task_id)["status"] == "awaiting_turn"

    suspended = client.post(f"/tasks/{task_id}/suspend", json={})
    assert suspended.status_code == 200
    resumed = client.post(f"/tasks/{task_id}/resume", json={})
    assert resumed.status_code == 200
    # The no-op resume parks the Segment back in awaiting_turn (not READY),
    # without re-invoking the model; repeated resumes are idempotent.
    assert resumed.json()["status"] == "awaiting_turn"
    assert counter["calls"] == 1
    again = client.post(f"/tasks/{task_id}/resume", json={})
    assert again.status_code == 409
    assert counter["calls"] == 1

    # A SECOND legitimate suspend/resume cycle must not collide with the
    # first marker's idempotency key: the stream stays contiguous and the
    # projection never runs past the Event Store.
    suspended2 = client.post(f"/tasks/{task_id}/suspend", json={})
    assert suspended2.status_code == 200
    resumed2 = client.post(f"/tasks/{task_id}/resume", json={})
    assert resumed2.status_code == 200
    assert resumed2.json()["status"] == "awaiting_turn"
    assert counter["calls"] == 1

    from agent_core.application.session_projection import rebuild_session
    from agent_storage import SQLiteEventStore

    events2 = SQLiteEventStore(tmp_path / "control.sqlite").list_for_session(
        SessionId(UUID(client.get(f"/tasks/{task_id}").json()["active_segment_id"]))
    )
    sequences = [event.sequence for event in events2]
    assert sequences == list(range(len(sequences)))
    projection = rebuild_session(events2)
    assert projection.current_sequence == sequences[-1]
    assert projection.status.value == "awaiting_turn"

    cancelled = client.post(f"/tasks/{task_id}/cancel", json={})

    assert cancelled.status_code == 200
    detail = client.get(f"/tasks/{task_id}").json()
    assert detail["status"] == "cancelled"
    assert detail["task_status"] == "cancelled"

    # Scenario A: cancelled while awaiting_turn with NO open Turn —
    # the Segment terminal stands alone.
    events_after_cancel = SQLiteEventStore(tmp_path / "control.sqlite").list_for_session(
        SessionId(UUID(detail["active_segment_id"]))
    )
    tail_types = [event.event_type.value for event in events_after_cancel]
    assert tail_types[-1] == "session_cancelled"
    assert "turn_cancelled" not in tail_types

def test_cancel_after_follow_up_message_writes_turn_cancelled(
    tmp_path: Path, monkeypatch
) -> None:
    """Scenario B: READY with an open follow-up Turn cancels both levels."""
    counter: dict[str, int] = {"calls": 0}
    _counting_gateway(monkeypatch, counter, "Turn one done.")
    client = TestClient(create_http_app(tmp_path / "cancel-open.sqlite", settings=_settings(None)))
    task_id = _create_conversation_task(client, workspace_root=tmp_path)
    assert _run_turn(client, task_id)["status"] == "awaiting_turn"

    follow_up = client.post(f"/tasks/{task_id}/messages", json={"content": "Next round."})
    assert follow_up.status_code == 201

    cancelled = client.post(f"/tasks/{task_id}/cancel", json={})

    assert cancelled.status_code == 200
    detail = client.get(f"/tasks/{task_id}").json()
    assert detail["status"] == "cancelled"
    assert detail["current_turn_status"] == "cancelled"

    from agent_core.application.session_projection import rebuild_session
    from agent_storage import SQLiteEventStore

    events = SQLiteEventStore(tmp_path / "cancel-open.sqlite").list_for_session(
        SessionId(UUID(detail["active_segment_id"]))
    )
    tail_types = [event.event_type.value for event in events]
    assert tail_types[-2:] == ["turn_cancelled", "session_cancelled"]
    # the stream stays contiguous for replay
    sequences = [event.sequence for event in events]
    assert sequences == list(range(len(sequences)))
    rebuild_session(events)
