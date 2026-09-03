"""ADR-026 concurrency and crash-window acceptance (full Worker)."""

from pathlib import Path
from types import SimpleNamespace
from uuid import UUID

import zebra_agent_worker.execution as worker_execution_module
from agent_core.domain.turns import InteractionMode
from agent_security import parse_network_profile
from fastapi.testclient import TestClient
from http_app_support import (
    _counting_gateway,
    _create_conversation_task,
    _run_turn,
    _settings,
)
from zebra_agent_api import create_http_app
from zebra_agent_config import ZebraAgentSettings


def test_concurrent_follow_up_arriving_after_claim_executes_the_new_turn(
    tmp_path: Path, monkeypatch
) -> None:
    """Full Worker: a message landing after the claim/snapshot wins.

    The first recover_execution_inputs call returns the PRE-message
    snapshot (old Task, old events) exactly as if the follow-up landed
    right after the claim; the durable stream already contains it. The
    stale request must NOT execute — the Worker re-recovers and runs the
    NEW Turn.
    """
    counter: dict[str, int] = {"calls": 0}
    gateways: list = []
    _counting_gateway(
        monkeypatch,
        counter,
        "Turn one done.",
        "NEW TURN ANSWER",
        gateways=gateways,
    )
    client = TestClient(create_http_app(tmp_path / "race.sqlite", settings=_settings(None)))
    task_id = _create_conversation_task(client, workspace_root=tmp_path)
    assert _run_turn(client, task_id)["status"] == "awaiting_turn"

    import zebra_agent_worker.execution as execution_module
    from agent_core.application.session_projection import rebuild_session
    from agent_core.application.workspace_projection import rebuild_workspace
    from agent_core.domain.events import EventActor, EventType, SessionEvent
    from agent_core.domain.identifiers import SessionId
    from agent_core.domain.turns import derive_turn_id
    from agent_storage import SQLiteEventStore, SQLiteProjectionStore

    database_path = tmp_path / "race.sqlite"
    session_id = SessionId(UUID(client.get(f"/tasks/{task_id}").json()["active_segment_id"]))
    event_store = SQLiteEventStore(database_path)
    second_turn = str(derive_turn_id(session_id, 1))

    # The follow-up lands (durable stream + projection become READY)...
    events = event_store.list_for_session(session_id)
    event_store.append(
        SessionEvent.create(
            session_id=session_id,
            sequence=events[-1].sequence + 1,
            event_type=EventType.USER_MESSAGE_RECEIVED,
            actor=EventActor.USER,
            payload={
                "content": "NEW CONCURRENT FOLLOW-UP",
                "turn_id": second_turn,
                "turn_index": 1,
                "origin": "human",
            },
        )
    )
    SQLiteProjectionStore(database_path).save_session(
        rebuild_session(event_store.list_for_session(session_id))
    )
    # ...but the execution inputs were snapshotted BEFORE it: a stale
    # claimed state (awaiting_turn) and the pre-message event list.
    follow_up_sequence = events[-1].sequence + 1
    stale_events = [
        e for e in event_store.list_for_session(session_id) if e.sequence < follow_up_sequence
    ]
    stale_session = rebuild_session(stale_events)
    stale_workspace = rebuild_workspace(stale_events)
    stale_inputs = SimpleNamespace(
        claimed=SimpleNamespace(
            recovery=SimpleNamespace(session=stale_session, workspace=stale_workspace),
            lease=SimpleNamespace(fence=None),
        ),
        session_events=stale_events,
        provider_continuation=None,
        cloud_continuation=None,
        task=SimpleNamespace(
            network_profile=parse_network_profile("none"),
            interaction_mode=InteractionMode.CONVERSATION,
        ),
        active_capsule=None,
        recovered_handoff=None,
    )
    original_recovery = execution_module.recover_execution_inputs
    served = {"stale": False}

    def recovery_with_stale_snapshot(**kwargs):
        if not served["stale"]:
            served["stale"] = True
            return stale_inputs
        return original_recovery(**kwargs)

    monkeypatch.setattr(
        execution_module, "recover_execution_inputs", recovery_with_stale_snapshot
    )

    response = client.post(f"/tasks/{task_id}/resume", json={})

    assert response.status_code == 200, response.text
    # The stale "no open turn" snapshot was NOT executed; the new Turn ran.
    assert counter["calls"] == 2

    # Prove the MODEL actually received the new message: the fresh-run
    # gateway's execution requests contain the follow-up as the last USER
    # message and the completed first Turn as valid conversation history.
    from agent_core.domain.messages import MessageRole

    fresh_requests = gateways[-1].requests
    assert fresh_requests, "the fresh gateway saw no model request"
    user_messages = [
        message.content
        for request in fresh_requests
        for message in request
        if message.role is MessageRole.USER
    ]
    assert "NEW CONCURRENT FOLLOW-UP" in user_messages
    assert any("codeword" in content for content in user_messages)
    events_after = event_store.list_for_session(session_id)
    closes = [event for event in events_after if event.event_type.value == "turn_completed"]
    assert len(closes) == 2
    assert closes[-1].payload["turn_id"] == second_turn
    assert closes[-1].payload["closes_segment"] is False
    human_messages = [
        event.payload["content"]
        for event in events_after
        if event.event_type.value == "user_message_received"
        and event.payload.get("origin") == "human"
    ]
    assert human_messages[-1] == "NEW CONCURRENT FOLLOW-UP"
    sequences = [event.sequence for event in events_after]
    assert sequences == list(range(len(sequences)))
    rebuild_session(events_after)

def test_crashed_turn_cancelled_window_is_healed(tmp_path: Path, monkeypatch) -> None:
    def failing_gateway(_settings: ZebraAgentSettings):
        raise AssertionError("cancelled-window reconciliation must not call the model")

    monkeypatch.setattr(worker_execution_module, "build_model_gateway", failing_gateway)

    from agent_core.application import SessionBootstrapCommand, SessionBootstrapService
    from agent_core.application.session_projection import rebuild_session
    from agent_core.domain.events import EventActor, EventType, SessionEvent
    from agent_core.domain.turns import derive_turn_id
    from agent_storage import SQLiteEventStore, SQLiteProjectionStore

    database_path = tmp_path / "heal-cancelled.sqlite"
    bootstrap = SessionBootstrapService().build(
        SessionBootstrapCommand(
            title="Crashed cancel",
            user_input="Do the work.",
            workspace_root=tmp_path,
        )
    )
    event_store = SQLiteEventStore(database_path)
    for event in bootstrap.events:
        event_store.append(event)
    session = bootstrap.session
    event_store.append(
        SessionEvent.create(
            session_id=session.session_id,
            sequence=session.current_sequence + 1,
            event_type=EventType.HARNESS_ATTEMPT_STARTED,
            actor=EventActor.HARNESS,
            payload={"attempt_number": 1},
        )
    )
    # Control plane crashed after TURN_CANCELLED, before SESSION_CANCELLED.
    event_store.append(
        SessionEvent.create(
            session_id=session.session_id,
            sequence=session.current_sequence + 2,
            event_type=EventType.TURN_CANCELLED,
            actor=EventActor.SYSTEM,
            payload={
                "turn_id": str(derive_turn_id(session.session_id, 0)),
                "turn_index": 0,
                "reason": "session_cancelled",
            },
        )
    )
    healed = rebuild_session(event_store.list_for_session(session.session_id))
    SQLiteProjectionStore(database_path).save_session(healed)

    client = TestClient(create_http_app(database_path, settings=_settings(None)))
    response = client.post(f"/sessions/{session.session_id}/resume", json={})

    assert response.status_code == 200
    assert response.json()["status"] == "cancelled"
    events = event_store.list_for_session(session.session_id)
    assert [event.event_type for event in events[-2:]] == [
        EventType.TURN_CANCELLED,
        EventType.SESSION_CANCELLED,
    ]

def test_pending_turn_close_reconciles_end_to_end_on_setup_only_stream(
    tmp_path: Path, monkeypatch
) -> None:
    """End-to-end healing on a setup-only stream.

    The SQLite API composition always has a local Artifact store, so the
    capability rejection itself cannot fire here; the reconcile-before-
    capability ordering is proven by
    tests/worker/test_execution_preflight_order.py.
    """

    def failing_gateway(_settings: ZebraAgentSettings):
        raise AssertionError("reconciliation must precede any new attempt")

    monkeypatch.setattr(worker_execution_module, "build_model_gateway", failing_gateway)

    from agent_core.application import SessionBootstrapCommand, SessionBootstrapService
    from agent_core.application.session_projection import rebuild_session
    from agent_core.domain.events import EventActor, EventType, SessionEvent
    from agent_core.domain.turns import derive_turn_id
    from agent_storage import SQLiteEventStore, SQLiteProjectionStore

    database_path = tmp_path / "heal-capability.sqlite"
    # setup-only would fail preflight; the durable success must win first.
    bootstrap = SessionBootstrapService().build(
        SessionBootstrapCommand(
            title="Healed before capability",
            user_input="Do the work.",
            workspace_root=tmp_path,
            network_profile="setup-only",
        )
    )
    event_store = SQLiteEventStore(database_path)
    for event in bootstrap.events:
        event_store.append(event)
    session = bootstrap.session
    event_store.append(
        SessionEvent.create(
            session_id=session.session_id,
            sequence=session.current_sequence + 1,
            event_type=EventType.HARNESS_ATTEMPT_STARTED,
            actor=EventActor.HARNESS,
            payload={"attempt_number": 1},
        )
    )
    event_store.append(
        SessionEvent.create(
            session_id=session.session_id,
            sequence=session.current_sequence + 2,
            event_type=EventType.TURN_COMPLETED,
            actor=EventActor.HARNESS,
            payload={
                "turn_id": str(derive_turn_id(session.session_id, 0)),
                "turn_index": 0,
                "summary": "Already done.",
                "closes_segment": True,
            },
        )
    )
    healed = rebuild_session(event_store.list_for_session(session.session_id))
    SQLiteProjectionStore(database_path).save_session(healed)

    client = TestClient(create_http_app(database_path, settings=_settings(None)))
    response = client.post(f"/sessions/{session.session_id}/resume", json={})

    assert response.status_code == 200
    assert response.json()["status"] == "completed"
    events = event_store.list_for_session(session.session_id)
    event_types = [event.event_type.value for event in events]
    assert "session_failed" not in event_types
    assert event_types[-1] == "session_completed"

def test_crashed_failed_turn_close_is_healed_without_model_call(
    tmp_path: Path, monkeypatch
) -> None:
    def failing_gateway(_settings: ZebraAgentSettings):
        raise AssertionError("failed-turn reconciliation must not call the model")

    monkeypatch.setattr(worker_execution_module, "build_model_gateway", failing_gateway)

    from agent_core.application import SessionBootstrapCommand, SessionBootstrapService
    from agent_core.application.session_projection import rebuild_session
    from agent_core.domain.events import EventActor, EventType, SessionEvent
    from agent_core.domain.turns import derive_turn_id
    from agent_storage import SQLiteEventStore, SQLiteProjectionStore

    database_path = tmp_path / "heal-failed.sqlite"
    bootstrap = SessionBootstrapService().build(
        SessionBootstrapCommand(
            title="Crashed failure",
            user_input="Do the work.",
            workspace_root=tmp_path,
        )
    )
    event_store = SQLiteEventStore(database_path)
    for event in bootstrap.events:
        event_store.append(event)
    session = bootstrap.session
    attempt = SessionEvent.create(
        session_id=session.session_id,
        sequence=session.current_sequence + 1,
        event_type=EventType.HARNESS_ATTEMPT_STARTED,
        actor=EventActor.HARNESS,
        payload={"attempt_number": 1},
    )
    event_store.append(attempt)
    turn = SessionEvent.create(
        session_id=session.session_id,
        sequence=attempt.sequence + 1,
        event_type=EventType.TURN_FAILED,
        actor=EventActor.HARNESS,
        payload={
            "turn_id": str(derive_turn_id(session.session_id, 0)),
            "turn_index": 0,
            "reason": "provider failed; worker crashed before the terminal.",
            "closes_segment": True,
        },
    )
    event_store.append(turn)
    healed = rebuild_session(event_store.list_for_session(session.session_id))
    SQLiteProjectionStore(database_path).save_session(healed)

    client = TestClient(create_http_app(database_path, settings=_settings(None)))
    response = client.post(f"/sessions/{session.session_id}/resume", json={})

    assert response.status_code == 200, response.text
    assert response.json()["status"] == "failed"
    events = event_store.list_for_session(session.session_id)
    assert [event.event_type for event in events[-2:]] == [
        EventType.TURN_FAILED,
        EventType.SESSION_FAILED,
    ]

def test_crashed_one_shot_turn_close_is_healed_without_model_call(
    tmp_path: Path, monkeypatch
) -> None:
    def failing_gateway(_settings: ZebraAgentSettings):
        raise AssertionError("reconciliation must not call the model")

    monkeypatch.setattr(worker_execution_module, "build_model_gateway", failing_gateway)

    from agent_core.application import SessionBootstrapCommand, SessionBootstrapService
    from agent_core.domain.events import EventActor, EventType, SessionEvent
    from agent_core.domain.turns import derive_turn_id
    from agent_storage import SQLiteEventStore, SQLiteProjectionStore

    database_path = tmp_path / "heal.sqlite"
    bootstrap = SessionBootstrapService().build(
        SessionBootstrapCommand(
            title="Crashed close",
            user_input="Do the work.",
            workspace_root=tmp_path,
        )
    )
    event_store = SQLiteEventStore(database_path)
    for event in bootstrap.events:
        event_store.append(event)
    session = bootstrap.session
    attempt = SessionEvent.create(
        session_id=session.session_id,
        sequence=session.current_sequence + 1,
        event_type=EventType.HARNESS_ATTEMPT_STARTED,
        actor=EventActor.HARNESS,
        payload={"attempt_number": 1},
    )
    event_store.append(attempt)
    turn = SessionEvent.create(
        session_id=session.session_id,
        sequence=attempt.sequence + 1,
        event_type=EventType.TURN_COMPLETED,
        actor=EventActor.HARNESS,
        payload={
            "turn_id": str(derive_turn_id(session.session_id, 0)),
            "turn_index": 0,
            "summary": "Model finished; worker crashed before the terminal.",
            "closes_segment": True,
        },
    )
    event_store.append(turn)
    from agent_core.application.session_projection import rebuild_session

    healed_session = rebuild_session(event_store.list_for_session(session.session_id))
    SQLiteProjectionStore(database_path).save_session(healed_session)
    assert healed_session.status.value == "running"

    client = TestClient(create_http_app(database_path, settings=_settings(None)))
    response = client.post(f"/sessions/{session.session_id}/resume", json={})

    assert response.status_code == 200
    assert response.json()["status"] == "completed"
    events = event_store.list_for_session(session.session_id)
    assert [event.event_type for event in events[-2:]] == [
        EventType.TURN_COMPLETED,
        EventType.SESSION_COMPLETED,
    ]


def test_next_message_during_finalization_tail_defers_instead_of_crashing(
    tmp_path: Path, monkeypatch
) -> None:
    """The review-reproduced P1: the next human message races the
    memory/title tail (an LLM round-trip wide) and wins the sequence.

    The Turn outcome is already durable; losing the tail race must defer
    the auxiliary side chain (recovery re-drives it) instead of crashing
    the worker run.
    """
    gateways: list = []
    counter: dict[str, int] = {"calls": 0}
    _counting_gateway(
        monkeypatch,
        counter,
        "Turn one done.",
        "Turn two done.",
        gateways=gateways,
    )
    client = TestClient(create_http_app(tmp_path / "tail.sqlite", settings=_settings(None)))
    task_id = _create_conversation_task(client, workspace_root=tmp_path)

    import zebra_agent_worker.execution as execution_module
    from agent_core.application.session_projection import rebuild_session
    from agent_core.domain.events import EventActor, EventType, SessionEvent
    from agent_core.domain.identifiers import SessionId
    from agent_core.domain.turns import derive_turn_id
    from agent_storage import SQLiteEventStore, SQLiteProjectionStore

    database_path = tmp_path / "tail.sqlite"
    session_id = SessionId(
        UUID(client.get(f"/tasks/{task_id}").json()["active_segment_id"])
    )
    event_store = SQLiteEventStore(database_path)
    original_title_service = execution_module.SessionTitleService

    class _RacingTitleService(original_title_service):
        def generate(self, *args, **kwargs):
            # The next message lands while the title LLM call is in
            # flight — exactly the review's reproduction.
            events = event_store.list_for_session(session_id)
            event_store.append(
                SessionEvent.create(
                    session_id=session_id,
                    sequence=events[-1].sequence + 1,
                    event_type=EventType.USER_MESSAGE_RECEIVED,
                    actor=EventActor.USER,
                    payload={
                        "content": "NEXT WHILE FINALIZING",
                        "turn_id": str(derive_turn_id(session_id, 1)),
                        "turn_index": 1,
                        "origin": "human",
                    },
                )
            )
            SQLiteProjectionStore(database_path).save_session(
                rebuild_session(event_store.list_for_session(session_id))
            )
            return super().generate(*args, **kwargs)

    monkeypatch.setattr(
        execution_module, "SessionTitleService", _RacingTitleService
    )

    first = client.post(f"/tasks/{task_id}/resume", json={})

    assert first.status_code == 200, first.text
    # The racing message already re-armed the Segment, so the reported
    # status comes from the durable projection (ready), not the stale
    # in-recorder awaiting_turn — either is correct here.
    assert first.json()["status"] in {"awaiting_turn", "ready"}
    events = event_store.list_for_session(session_id)
    closes = [e for e in events if e.event_type.value == "turn_completed"]
    assert len(closes) == 1  # turn 1 closed, no duplicate close
    human = [
        e.payload["content"]
        for e in events
        if e.event_type.value == "user_message_received"
        and e.payload.get("origin") == "human"
    ]
    assert human[-1] == "NEXT WHILE FINALIZING"
    sequences = [e.sequence for e in events]
    assert sequences == list(range(len(sequences)))
    rebuild_session(events)

    # The racing turn executes normally on the next resume.
    monkeypatch.setattr(execution_module, "SessionTitleService", original_title_service)
    second = client.post(f"/tasks/{task_id}/resume", json={})
    assert second.status_code == 200
    assert second.json()["status"] == "awaiting_turn"
    events = event_store.list_for_session(session_id)
    closes = [e for e in events if e.event_type.value == "turn_completed"]
    assert len(closes) == 2
    assert closes[-1].payload["turn_id"] == str(derive_turn_id(session_id, 1))
    sequences = [e.sequence for e in events]
    assert sequences == list(range(len(sequences)))
    rebuild_session(events)
