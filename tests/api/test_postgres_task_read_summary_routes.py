"""Verified Host/native cloud GET plus actual bounded background summary preparation."""

import os

import pytest
from agent_core.application import current_turn, interaction_mode_of, project_turns
from agent_core.application.session_attachments import attach_refs_to_user_event
from agent_core.domain.attachments import SessionAttachmentRef
from agent_core.domain.events import EventActor, EventType, SessionEvent
from agent_core.domain.identifiers import TaskId, new_artifact_id
from agent_integrations.ag_ui.checkpoint_consumer import AgUiCheckpointConsumer

from tests.api.ag_ui_checkpoint_postgres_support import (
    PgSqlObservation,
    pg_rows,
)
from tests.api.ag_ui_checkpoint_postgres_support import (
    pg_get_replay as _pg_fixture,
)
from tests.api.test_extension_reads import AUTH

native_pg_get_replay = _pg_fixture


@pytest.fixture
def pg_get_replay(request):
    if not os.environ.get("ZEBRA_HEADER_SCRATCH_DSN"):
        pytest.skip("requires the explicitly isolated header_scratch PG database")
    return request.getfixturevalue("native_pg_get_replay")


def prepare_source(replay):
    stores = replay.stores()
    task = stores.tasks.ensure_for_session(replay.session)
    while not stores.tasks.backfill_event_positions(task.task_id):
        pass
    page = stores.tasks.read_event_page(task.task_id, -1)
    sequence = page.events[-1].segment_sequence + 1
    event = SessionEvent.create(
        session_id=replay.session,
        sequence=sequence,
        actor=EventActor.USER,
        event_type=EventType.USER_MESSAGE_RECEIVED,
        payload={"content": "Read this attachment"},
    )
    reference = SessionAttachmentRef(
        attachment_id=new_artifact_id(),
        message_event_id=event.event_id,
        file_name="brief.txt",
        media_type="text/plain",
        size_bytes=5,
        sha256="a" * 64,
    )
    stores.events.append(attach_refs_to_user_event(event, (reference,)))
    stores.events.append(
        SessionEvent.create(
            session_id=replay.session,
            sequence=sequence + 1,
            actor=EventActor.HARNESS,
            event_type=EventType.MODEL_RESPONSE_RECEIVED,
            payload={"input_tokens": 123, "resolved_model": "main", "prompt_cache_hit_tokens": 9},
        )
    )
    return stores, task, reference


def test_native_cloud_usage_and_attachments_get_is_readonly_and_body_free(
    pg_get_replay, monkeypatch
):
    replay = pg_get_replay
    stores, task, reference = prepare_source(replay)
    # Production consumer path, not hand-written summary/checkpoint preparation.
    work = stores.projection_work
    assert work is not None
    work.enable_projection_work()
    consumer = AgUiCheckpointConsumer(
        stores.tasks,
        work,
        namespace=replay.cloud.deployment_namespace,
        read_summaries=stores.tasks,
    )
    for _ in range(16):
        work.bootstrap_projection_work(limit=32)
        consumer.poll_once(budget_seconds=2)
        if stores.tasks.read_task_summary(task.task_id).complete:
            break
    assert stores.tasks.read_task_summary(task.task_id).complete
    before = pg_rows(replay.dsn)
    client = replay.client()
    with monkeypatch.context() as patch:
        observation = PgSqlObservation(patch)
        usage = client.get(f"/tasks/{task.task_id}/usage", headers=AUTH)
        attachments = client.get(f"/tasks/{task.task_id}/attachments", headers=AUTH)
        assert usage.status_code == attachments.status_code == 200
        assert usage.json()["model_usage"] == {
            "model_call_count": 1,
            "cache_hit_tokens": 9,
            "cache_miss_tokens": 0,
            "input_tokens": 123,
            "model": "main",
        }
        assert attachments.json()["attachments"] == [reference.to_mapping()]
        assert attachments.json()["has_more"] is False
        assert not observation.writes and not observation.body_reads
        assert observation.connections == {"TaskIoConnection"}
    assert pg_rows(replay.dsn) == before


def test_native_cloud_full_task_get_keeps_turn_truth_without_history_hydration(
    pg_get_replay, monkeypatch
):
    replay = pg_get_replay
    stores, task, _ = prepare_source(replay)
    while not stores.tasks.backfill_read_summary(task.task_id):
        pass
    source = stores.events.list_for_session(replay.session)
    turns = project_turns(source)
    visible = current_turn(source) or (turns[-1] if turns else None)

    def forbidden(*args, **kwargs):
        pytest.fail("cloud Task GET hydrated complete history for Turn fields")

    monkeypatch.setattr(type(stores.events), "list_for_session", forbidden)
    monkeypatch.setattr(type(stores.tasks), "read_events", forbidden)
    before = pg_rows(replay.dsn)
    client = replay.client()
    with monkeypatch.context() as patch:
        observation = PgSqlObservation(patch)
        response = client.get(f"/tasks/{task.task_id}", headers=AUTH)
        assert response.status_code == 200
        body = response.json()
        assert body["interaction_mode"] == interaction_mode_of(source).value
        assert body["turn_id"] == (visible.turn_id if visible else None)
        assert body["current_turn_status"] == (visible.status.value if visible else None)
        assert not observation.writes and not observation.body_reads
        assert observation.connections == {"TaskIoConnection"}
    assert pg_rows(replay.dsn) == before


def test_native_cloud_pending_get_does_not_prepare_summary(pg_get_replay, monkeypatch):
    replay = pg_get_replay
    stores, task, _ = prepare_source(replay)
    assert stores.tasks.read_task_summary(task.task_id).through_sequence == -1
    client = replay.client()
    before = pg_rows(replay.dsn)
    with monkeypatch.context() as patch:
        observation = PgSqlObservation(patch)
        for suffix in ("", "/usage", "/attachments"):
            response = client.get(f"/tasks/{task.task_id}{suffix}", headers=AUTH)
            assert response.status_code == 409
            assert response.json()["status"] == "projection_incomplete"
            assert response.json()["code"] == "projection_not_ready"
            assert response.json()["retryable"] is True
        assert not observation.writes and not observation.body_reads
    assert pg_rows(replay.dsn) == before
    assert stores.tasks.read_task_summary(TaskId(replay.session)).through_sequence == -1
