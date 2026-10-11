"""Native SQLite usage/attachment frontiers are bounded, persistent and GET-read-only."""

import json
import sqlite3
from contextlib import contextmanager
from hashlib import sha256

import pytest
from agent_core.application import attachment_refs_from_event
from agent_core.application.session_attachments import attach_refs_to_user_event
from agent_core.domain.attachments import SessionAttachmentRef
from agent_core.domain.events import EventActor, EventType, SessionEvent
from agent_core.domain.identifiers import new_artifact_id
from agent_core.domain.turns import derive_turn_id
from agent_core.ports.task_projection_checkpoints import CheckpointConflict
from agent_storage import SQLiteAgentTaskStore, SQLiteEventStore
from zebra_agent_api.task_model_usage import summarize_task_model_usage

from tests.agent_storage.test_task_event_pages import _task


def summary_store(tmp_path, count=3):
    store, task = _task(tmp_path / "summaries.sqlite", count)
    return store, task


def append_attachment(store, task, name="brief.txt"):
    header = store.read_task_header(task.task_id)
    source = store.read_event_page(task.task_id, header.current_sequence - 1, limit=1).events[0]
    event = SessionEvent.create(
        session_id=task.active_segment_id,
        sequence=source.segment_sequence + 1,
        actor=EventActor.USER,
        event_type=EventType.USER_MESSAGE_RECEIVED,
        payload={"content": "Read"},
    )
    ref = SessionAttachmentRef(
        attachment_id=new_artifact_id(),
        message_event_id=event.event_id,
        file_name=name,
        media_type="text/plain",
        size_bytes=5,
        sha256=sha256(b"hello").hexdigest(),
    )
    event = attach_refs_to_user_event(event, (ref,))
    SQLiteEventStore(store._database.database_path).append(event)
    return event


def repair(store, task):
    for _ in range(100):
        if store.backfill_read_summary(task.task_id, limit=2):
            return
    pytest.fail("bounded summary repair failed to converge")


def test_summary_pending_is_not_an_empty_success_and_repair_is_idempotent(tmp_path):
    store, task = summary_store(tmp_path, 8)
    assert not store.read_task_summary(task.task_id).complete
    assert not store.backfill_read_summary(task.task_id, limit=2)
    partial = store.read_task_summary(task.task_id)
    assert partial.through_sequence == 1 and not partial.complete
    repair(store, task)
    complete = store.read_task_summary(task.task_id)
    assert complete.complete and complete.through_sequence == 7
    assert store.backfill_read_summary(task.task_id)
    assert store.read_task_summary(task.task_id) == complete


def test_turn_fields_are_persisted_and_cold_read_does_not_hydrate_events(tmp_path, monkeypatch):
    store, task = summary_store(tmp_path)
    turn_id = str(derive_turn_id(task.active_segment_id, 0))
    SQLiteEventStore(store._database.database_path).append(
        SessionEvent.create(
            session_id=task.active_segment_id,
            sequence=3,
            actor=EventActor.USER,
            event_type=EventType.USER_MESSAGE_RECEIVED,
            payload={"content": "Next", "turn_id": turn_id, "turn_index": 0, "origin": "human"},
        )
    )
    repair(store, task)
    cold = SQLiteAgentTaskStore(store._database.database_path)
    monkeypatch.setattr(cold, "read_events", lambda *a: pytest.fail("whole history"))
    assert cold.read_task_summary(task.task_id).turn_fields == {
        "interaction_mode": "one_shot",
        "turn_id": turn_id,
        "current_turn_status": "running",
    }


def test_old_turn_summary_requires_bounded_rebuild_without_recounting_usage_or_refs(tmp_path):
    store, task = summary_store(tmp_path)
    append_attachment(store, task)
    repair(store, task)
    expected = store.read_task_summary(task.task_id)
    with store._database.connect() as connection:
        row = connection.execute("SELECT usage_state_json FROM task_read_summary_heads").fetchone()
        state = json.loads(row["usage_state_json"])
        state["turn_state"].pop("version")
        for segment in state["turn_state"]["segments"].values():
            segment.pop("lookup")
        connection.execute(
            "UPDATE task_read_summary_heads SET usage_state_json=?", (json.dumps(state),)
        )
    assert store.read_task_summary(task.task_id).turn_fields is None
    assert not store.backfill_read_summary(task.task_id, limit=1)
    assert store.read_task_summary(task.task_id).turn_fields is None
    repair(store, task)
    assert store.read_task_summary(task.task_id) == expected


def test_persisted_usage_matches_full_oracle_without_historical_payload_reads(
    tmp_path, monkeypatch
):
    store, task = summary_store(tmp_path)
    event = SessionEvent.create(
        session_id=task.active_segment_id,
        sequence=3,
        actor=EventActor.HARNESS,
        event_type=EventType.MODEL_RESPONSE_RECEIVED,
        payload={
            "resolved_model": "first",
            "input_tokens": 123,
            "prompt_cache_hit_tokens": 12,
            "prompt_cache_miss_tokens": 34,
        },
    )
    SQLiteEventStore(store._database.database_path).append(event)
    oracle = summarize_task_model_usage(store.read_events(task.task_id, -1))
    repair(store, task)
    original = store._database.connect
    queries = []

    @contextmanager
    def read_only():
        with original() as connection:

            def authorizer(action, table, column, database, context):
                if (
                    action == sqlite3.SQLITE_READ
                    and table == "session_events"
                    and column == "payload"
                ):
                    pytest.fail("summary GET read a canonical payload")
                if action in {sqlite3.SQLITE_INSERT, sqlite3.SQLITE_UPDATE, sqlite3.SQLITE_DELETE}:
                    pytest.fail("summary GET mutated storage")
                return sqlite3.SQLITE_OK

            connection.set_authorizer(authorizer)
            connection.set_trace_callback(queries.append)
            yield connection

    monkeypatch.setattr(store._database, "connect", read_only)
    assert store.read_task_summary(task.task_id).model_usage == oracle
    assert not any("COUNT(" in query or "length(" in query for query in queries)


def test_frozen_attachment_window_survives_append_and_cold_restore(tmp_path):
    store, task = summary_store(tmp_path)
    first = append_attachment(store, task, "first.txt")
    second = append_attachment(store, task, "second.txt")
    repair(store, task)
    page = store.read_attachment_page(task.task_id, limit=1)
    assert page.has_more and page.total_count == 2 and page.total_bytes == 10
    assert page.entries[0].attachment == attachment_refs_from_event(first)[0]
    append_attachment(store, task, "late.txt")
    repair(store, task)
    cold = SQLiteAgentTaskStore(store._database.database_path)
    tail = cold.read_attachment_page(
        task.task_id, page.next_ordinal, through_sequence=page.through_sequence
    )
    assert not tail.has_more and tail.total_count == 2
    assert tail.entries[0].attachment == attachment_refs_from_event(second)[0]
    assert store.read_attachment_page(task.task_id).total_count == 3


def test_attachment_byte_admission_precedes_reference_hydration(tmp_path, monkeypatch):
    store, task = summary_store(tmp_path)
    append_attachment(store, task)
    repair(store, task)
    from agent_storage import task_read_summaries

    monkeypatch.setattr(
        task_read_summaries, "attachment_from_row", lambda _: pytest.fail("hydrated")
    )
    with pytest.raises(CheckpointConflict, match="page budget"):
        store.read_attachment_page(task.task_id, max_bytes=1)


def test_missing_attachment_tail_is_not_a_short_success(tmp_path):
    store, task = summary_store(tmp_path)
    append_attachment(store, task)
    repair(store, task)
    with store._database.connect() as connection:
        connection.execute("DELETE FROM task_attachment_index")
    with pytest.raises(CheckpointConflict, match="coverage"):
        store.read_attachment_page(task.task_id)


def test_missing_last_row_cannot_be_a_short_nonempty_page(tmp_path):
    store, task = summary_store(tmp_path)
    append_attachment(store, task, "one.txt")
    append_attachment(store, task, "two.txt")
    repair(store, task)
    with store._database.connect() as connection:
        connection.execute("DELETE FROM task_attachment_index WHERE ordinal=1")
    with pytest.raises(CheckpointConflict, match="coverage"):
        store.read_attachment_page(task.task_id)


def test_older_attachment_frontier_still_matches_canonical_segment(tmp_path):
    store, task = summary_store(tmp_path)
    append_attachment(store, task, "one.txt")
    append_attachment(store, task, "two.txt")
    repair(store, task)
    with store._database.connect() as connection:
        connection.execute(
            "UPDATE task_read_summary_frontiers SET segment_sequence=segment_sequence+1 "
            "WHERE task_sequence=3",
        )
    with pytest.raises(CheckpointConflict, match="canonical"):
        store.read_attachment_page(task.task_id)


def test_resume_cursor_cannot_skip_a_missing_consumed_anchor(tmp_path):
    store, task = summary_store(tmp_path)
    append_attachment(store, task, "one.txt")
    append_attachment(store, task, "two.txt")
    repair(store, task)
    page = store.read_attachment_page(task.task_id)
    with store._database.connect() as connection:
        connection.execute("DELETE FROM task_attachment_index WHERE ordinal=1")
    with pytest.raises(CheckpointConflict, match="cursor"):
        store.read_attachment_page(task.task_id, 1, through_sequence=page.through_sequence)
