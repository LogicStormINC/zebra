"""Automatic Cloud commands need a persisted Run, including after create replay."""

from uuid import UUID

import pytest
from agent_core.domain.events import EventType
from agent_core.domain.identifiers import SessionId
from agent_storage import sqlite_control_plane_stores
from zebra_agent_api import create_app


@pytest.mark.parametrize("key", [None, "create-key", "k" * 256])
def test_automatic_run_has_canonical_identity_and_replay_never_requeues(tmp_path, key):
    database = tmp_path / "run.sqlite"
    app = create_app(database)
    created = app.create_session({"prompt": "Check sources", "workspace": str(tmp_path)})
    queued = app.queue_cloud_run(created, idempotency_key=key)
    assert queued.status_code == 201 and queued.body["status"] == "queued"
    session = SessionId(UUID(created.body["session_id"]))
    events = app.stores.events.list_for_session(session)
    accepted = [event for event in events if event.event_type is EventType.SESSION_COMMAND_ACCEPTED]
    assert len(accepted) == 1
    run_id = accepted[0].payload["payload"].get("run_id")
    assert isinstance(run_id, str) and run_id and run_id != str(session)
    cold = sqlite_control_plane_stores(database)
    task = cold.tasks.task_id_for_session(session)
    header = cold.tasks.read_latest_run_header(task)
    assert header.run_id == run_id and header.anchor.event_id == accepted[0].event_id
    replay = app.queue_cloud_run(created, idempotency_key=key)
    assert replay.body == queued.body
    assert app.stores.events.list_for_session(session) == events


def test_automatic_run_key_cannot_accept_foreign_run_meaning(tmp_path):
    app = create_app(tmp_path / "run.sqlite")
    created = app.create_session({"prompt": "Check sources", "workspace": str(tmp_path)})
    session = SessionId(UUID(created.body["session_id"]))
    before = app.stores.events.list_for_session(session)
    occupied = app.submit_command(
        str(session),
        {
            "kind": "run",
            "expected_revision": before[-1].sequence,
            "payload": {"run_id": "unrelated-explicit-run"},
        },
        idempotency_key="create-key:run",
    )
    assert occupied.status_code == 202
    events = app.stores.events.list_for_session(session)
    rejected = app.queue_cloud_run(created, idempotency_key="create-key")
    assert rejected.status_code == 409 and rejected.body["status"] == "idempotency_conflict"
    assert app.stores.events.list_for_session(session) == events
