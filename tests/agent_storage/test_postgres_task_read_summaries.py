"""Actual TaskIO, namespace, snapshot and bounded summary derivation contracts."""

import json
from concurrent.futures import ThreadPoolExecutor
from hashlib import sha256
from threading import Barrier
from time import monotonic
from uuid import uuid4

import psycopg
import pytest
from agent_core.application.session_attachments import attach_refs_to_user_event
from agent_core.domain.attachments import SessionAttachmentRef
from agent_core.domain.events import EventActor, EventType, SessionEvent
from agent_core.domain.identifiers import new_artifact_id
from agent_core.ports.task_projection_checkpoints import CheckpointConflict
from agent_storage import PostgresAgentTaskStore, PostgresEventStore
from agent_storage.postgres import task_read_summaries
from agent_storage.postgres.task_io import TaskIoConnection, task_io_deadline
from zebra_agent_api.task_model_usage import summarize_task_model_usage

from tests.agent_storage.test_postgres_task_event_pages import _task
from tests.api.test_postgres_host_auth_authorizer import dsn as _schema_fixture
from tests.api.test_postgres_host_auth_authorizer import postgres_dsn as _scratch_fixture

dsn = _schema_fixture
postgres_dsn = _scratch_fixture


def native_task(dsn, tmp_path, count=3):
    return _task(dsn, f"summary_{uuid4().hex}", tmp_path / "workspace", count)


def append(store, task, *, attachment=None, usage=None):
    highwater = store.read_event_page(task.task_id, -1, limit=1).highwater
    source = store.read_event_page(task.task_id, highwater - 1, limit=1).events[0]
    event = SessionEvent.create(
        session_id=task.active_segment_id,
        sequence=source.segment_sequence + 1,
        actor=EventActor.USER if attachment else EventActor.HARNESS,
        event_type=EventType.USER_MESSAGE_RECEIVED
        if attachment
        else EventType.MODEL_RESPONSE_RECEIVED,
        payload={"content": "Read"} if attachment else usage,
    )
    if attachment:
        ref = SessionAttachmentRef(
            attachment_id=new_artifact_id(),
            message_event_id=event.event_id,
            file_name=attachment,
            media_type="text/plain",
            size_bytes=5,
            sha256=sha256(b"hello").hexdigest(),
        )
        event = attach_refs_to_user_event(event, (ref,))
    PostgresEventStore(
        store._database._dsn,
        deployment_namespace=store._database.deployment_namespace,
    ).append(event)
    return event


def repair(store, task):
    for _ in range(100):
        if store.backfill_read_summary(task.task_id, limit=2):
            return
    pytest.fail("summary repair did not advance to its captured highwater")


def test_native_summary_is_pending_then_advances_bounded_idempotent_prefix(dsn, tmp_path):
    store, task = native_task(dsn, tmp_path, 8)
    assert not store.read_task_summary(task.task_id).complete
    assert not store.backfill_read_summary(task.task_id, limit=2)
    assert store.read_task_summary(task.task_id).through_sequence == 1
    repair(store, task)
    summary = store.read_task_summary(task.task_id)
    assert summary.complete and summary.through_sequence == 7
    assert store.backfill_read_summary(task.task_id)
    assert store.read_task_summary(task.task_id) == summary


def test_native_old_turn_summary_rebuilds_in_pages_without_recounting_usage_or_refs(dsn, tmp_path):
    store, task = native_task(dsn, tmp_path)
    append(store, task, attachment="one.txt")
    append(store, task, usage={"input_tokens": 123, "prompt_cache_hit_tokens": 9})
    repair(store, task)
    expected = store.read_task_summary(task.task_id)
    with store._database.connect() as connection:
        row = connection.execute("SELECT usage_state_json FROM task_read_summary_heads").fetchone()
        state = json.loads(row["usage_state_json"])
        state["turn_state"].pop("version")
        for segment in state["turn_state"]["segments"].values():
            segment.pop("lookup")
        connection.execute(
            "UPDATE task_read_summary_heads SET usage_state_json=%s", (json.dumps(state),)
        )
    assert store.read_task_summary(task.task_id).turn_fields is None
    assert not store.backfill_read_summary(task.task_id, limit=1)
    assert store.read_task_summary(task.task_id).turn_fields is None
    repair(store, task)
    assert store.read_task_summary(task.task_id) == expected


def test_native_usage_matches_oracle_and_get_uses_read_only_body_free_task_io(
    dsn, tmp_path, monkeypatch
):
    store, task = native_task(dsn, tmp_path)
    append(
        store,
        task,
        usage={
            "input_tokens": 123,
            "resolved_model": "main",
            "prompt_cache_hit_tokens": 12,
            "prompt_cache_miss_tokens": 9,
        },
    )
    oracle = summarize_task_model_usage(store.read_events(task.task_id, -1))
    repair(store, task)
    calls = []
    original = TaskIoConnection.execute

    def trace(connection, query, *args, **kwargs):
        text = str(query)
        calls.append(text)
        assert not text.lstrip().upper().startswith(("INSERT", "UPDATE", "DELETE"))
        assert "payload" not in text and "COUNT(" not in text and "length(" not in text
        return original(connection, query, *args, **kwargs)

    monkeypatch.setattr(TaskIoConnection, "execute", trace)
    assert store.read_task_summary(task.task_id).model_usage == oracle
    assert calls[0] == "SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY"


def test_native_frozen_pages_restore_from_new_facade_and_exclude_late_append(dsn, tmp_path):
    store, task = native_task(dsn, tmp_path)
    first = append(store, task, attachment="one.txt")
    second = append(store, task, attachment="two.txt")
    repair(store, task)
    page = store.read_attachment_page(task.task_id, limit=1)
    assert page.has_more and page.entries[0].attachment.message_event_id == first.event_id
    append(store, task, attachment="late.txt")
    repair(store, task)
    cold = PostgresAgentTaskStore(dsn, deployment_namespace=store._database.deployment_namespace)
    tail = cold.read_attachment_page(
        task.task_id,
        page.next_ordinal,
        through_sequence=page.through_sequence,
    )
    assert not tail.has_more and tail.total_count == 2 and tail.total_bytes == 10
    assert tail.entries[0].attachment.message_event_id == second.event_id
    assert cold.read_attachment_page(task.task_id).total_count == 3


def test_native_attachment_admission_precedes_json_loading(dsn, tmp_path, monkeypatch):
    store, task = native_task(dsn, tmp_path)
    append(store, task, attachment="one.txt")
    repair(store, task)
    queries = []
    original = TaskIoConnection.execute

    def trace(connection, query, *args, **kwargs):
        queries.append(str(query))
        return original(connection, query, *args, **kwargs)

    monkeypatch.setattr(TaskIoConnection, "execute", trace)
    monkeypatch.setattr(
        task_read_summaries, "attachment_from_row", lambda _: pytest.fail("decoded")
    )
    with pytest.raises(CheckpointConflict, match="page budget"):
        store.read_attachment_page(task.task_id, max_bytes=1)
    assert not any("a.ref_json" in query for query in queries)


def test_native_summary_namespace_and_invalid_window_are_denied(dsn, tmp_path):
    store, task = native_task(dsn, tmp_path)
    append(store, task, attachment="one.txt")
    repair(store, task)
    foreign = PostgresAgentTaskStore(dsn, deployment_namespace="foreign")
    assert foreign.read_task_summary(task.task_id) is None
    with pytest.raises(ValueError, match="not found"):
        foreign.read_attachment_page(task.task_id)
    with pytest.raises(ValueError, match="highwater"):
        store.read_attachment_page(task.task_id, through_sequence=99)


def test_native_summary_snapshot_survives_append_between_head_and_frontier(
    dsn, tmp_path, monkeypatch
):
    store, task = native_task(dsn, tmp_path)
    repair(store, task)
    original = task_read_summaries._head
    appended = False

    def append_after_read(connection, namespace, task_id, **kwargs):
        nonlocal appended
        row = original(connection, namespace, task_id, **kwargs)
        if not appended:
            appended = True
            append(store, task, attachment="concurrent.txt")
        return row

    monkeypatch.setattr(task_read_summaries, "_head", append_after_read)
    captured = store.read_task_summary(task.task_id)
    assert captured.complete and captured.attachment_count == 0
    fresh = store.read_task_summary(task.task_id)
    assert not fresh.complete and fresh.highwater == captured.highwater + 1


def test_native_concurrent_derivers_serialize_only_the_derived_head(dsn, tmp_path):
    store, task = native_task(dsn, tmp_path, 8)
    barrier = Barrier(2)

    def advance():
        barrier.wait(timeout=2)
        return store.backfill_read_summary(task.task_id, limit=2)

    with ThreadPoolExecutor(max_workers=2) as executor:
        results = tuple(executor.map(lambda _: advance(), range(2)))
    assert results == (False, False)
    assert store.read_task_summary(task.task_id).through_sequence == 3
    repair(store, task)
    assert store.read_task_summary(task.task_id).complete


def test_native_summary_head_lock_is_actually_cancelled_within_shared_deadline(dsn, tmp_path):
    store, task = native_task(dsn, tmp_path)
    repair(store, task)
    with store._database.connect() as locker:
        locker.execute(
            "SELECT task_id FROM task_read_summary_heads "
            "WHERE deployment_namespace=%s AND task_id=%s FOR UPDATE",
            (store._database.deployment_namespace, task.task_id),
        )
        start = monotonic()
        with (
            task_io_deadline(start + 0.2),
            pytest.raises(
                (TimeoutError, psycopg.errors.LockNotAvailable),
            ),
        ):
            store.backfill_read_summary(task.task_id)
        assert monotonic() - start < 1
    assert store.read_task_summary(task.task_id).complete


def test_native_short_nonempty_page_is_missing_coverage(dsn, tmp_path):
    store, task = native_task(dsn, tmp_path)
    append(store, task, attachment="one.txt")
    append(store, task, attachment="two.txt")
    repair(store, task)
    with store._database.connect() as connection:
        connection.execute(
            "DELETE FROM task_attachment_index WHERE deployment_namespace=%s AND task_id=%s "
            "AND ordinal=1",
            (store._database.deployment_namespace, task.task_id),
        )
    with pytest.raises(CheckpointConflict, match="coverage"):
        store.read_attachment_page(task.task_id)


def test_native_older_attachment_frontier_requires_exact_canonical_coordinates(dsn, tmp_path):
    store, task = native_task(dsn, tmp_path)
    first = append(store, task, attachment="one.txt")
    append(store, task, attachment="two.txt")
    repair(store, task)
    with store._database.connect() as connection:
        connection.execute(
            "UPDATE task_read_summary_frontiers SET segment_sequence=segment_sequence+1 "
            "WHERE deployment_namespace=%s AND task_id=%s AND event_id=%s",
            (store._database.deployment_namespace, task.task_id, first.event_id),
        )
    with pytest.raises(CheckpointConflict, match="canonical"):
        store.read_attachment_page(task.task_id)


def test_native_resume_cursor_cannot_skip_a_missing_consumed_anchor(dsn, tmp_path):
    store, task = native_task(dsn, tmp_path)
    append(store, task, attachment="one.txt")
    repair(store, task)
    page = store.read_attachment_page(task.task_id)
    with store._database.connect() as connection:
        connection.execute(
            "DELETE FROM task_attachment_index WHERE deployment_namespace=%s AND task_id=%s",
            (store._database.deployment_namespace, task.task_id),
        )
    with pytest.raises(CheckpointConflict, match="cursor"):
        store.read_attachment_page(task.task_id, 0, through_sequence=page.through_sequence)
