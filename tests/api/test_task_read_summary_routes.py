"""Actual facade-backed read routes never repair or claim a page is all attachments."""

import base64
import json
import sqlite3
from contextlib import contextmanager

import pytest
from agent_core.domain.events import EventActor, EventType, SessionEvent
from agent_core.ports.task_projection_checkpoints import CheckpointConflict
from agent_storage import SQLiteEventStore, sqlite_control_plane_stores
from zebra_agent_api import RouteAdapter, RouteRequest, create_app
from zebra_agent_api.task_model_usage import summarize_task_model_usage
from zebra_agent_api.task_read_summaries import read_task_usage

from tests.agent_storage.test_task_read_summaries import append_attachment, repair, summary_store


def adapter(store):
    stores = sqlite_control_plane_stores(store._database.database_path)
    return RouteAdapter(create_app(store._database.database_path, stores=stores))


def test_pending_attachments_do_not_read_payloads_or_repair(tmp_path, monkeypatch):
    store, task = summary_store(tmp_path)
    api = adapter(store)

    def forbidden(*args, **kwargs):
        pytest.fail("GET attempted history hydration or explicit preparation")

    for method in ("read_events", "read_event_page", "backfill_read_summary"):
        monkeypatch.setattr(api.app.stores.tasks, method, forbidden)
    monkeypatch.setattr(api.app.stores.events, "list_for_session", forbidden)
    for suffix in ("/attachments",):
        response = api.handle(RouteRequest("GET", f"/tasks/{task.task_id}{suffix}"))
        assert response.status_code == 409 and response.body["status"] == "projection_incomplete"
        assert response.body["code"] == "projection_not_ready"
        assert response.body["retryable"] is True
    assert store.read_task_summary(task.task_id).through_sequence == -1


def test_attachment_cursor_preserves_frozen_window_across_real_source_append(tmp_path):
    store, task = summary_store(tmp_path)
    append_attachment(store, task, "one.txt")
    second = append_attachment(store, task, "two.txt")
    repair(store, task)
    api = adapter(store)
    first = api.handle(
        RouteRequest("GET", f"/tasks/{task.task_id}/attachments", query={"limit": "1"})
    )
    assert first.status_code == 200 and first.body["has_more"]
    assert first.body["attachment_count"] == 2 and first.body["attachment_bytes"] == 10
    cursor = first.body["next_cursor"]
    append_attachment(store, task, "late.txt")
    repair(store, task)
    tail = api.handle(
        RouteRequest(
            "GET",
            f"/tasks/{task.task_id}/attachments",
            query={"cursor": cursor},
        )
    )
    assert tail.status_code == 200 and tail.body["has_more"] is False
    assert tail.body["attachment_count"] == 2 and tail.body["next_cursor"] is None
    assert tail.body["attachments"][0]["message_event_id"] == str(second.event_id)
    assert tail.body["through_sequence"] == first.body["through_sequence"]


def test_cross_task_and_malformed_cursors_fail_before_ref_hydration(tmp_path, monkeypatch):
    store, task = summary_store(tmp_path)
    append_attachment(store, task, "one.txt")
    append_attachment(store, task, "two.txt")
    repair(store, task)
    api = adapter(store)
    first = api.handle(
        RouteRequest("GET", f"/tasks/{task.task_id}/attachments", query={"limit": "1"})
    )
    other, other_task = summary_store(tmp_path / "other")
    repair(other, other_task)
    other_api = adapter(other)
    denied = other_api.handle(
        RouteRequest(
            "GET",
            f"/tasks/{other_task.task_id}/attachments",
            query={"cursor": first.body["next_cursor"]},
        )
    )
    assert denied.status_code == 400
    monkeypatch.setattr(
        api.app.stores.tasks, "read_attachment_page", lambda *a, **k: pytest.fail("read")
    )
    data = {"v": 1, "task_id": str(task.task_id), "through_sequence": 10**30, "after_ordinal": 0}
    forged = base64.urlsafe_b64encode(json.dumps(data).encode()).decode()
    for cursor in ("!", "x" * 513, forged):
        assert (
            api.handle(
                RouteRequest(
                    "GET",
                    f"/tasks/{task.task_id}/attachments",
                    query={"cursor": cursor},
                )
            ).status_code
            == 400
        )


def test_real_usage_and_attachment_get_sql_is_read_only_and_body_free(tmp_path, monkeypatch):
    store, task = summary_store(tmp_path)
    append_attachment(store, task)
    repair(store, task)
    api = adapter(store)
    original = api.app.stores.tasks._database.connect

    @contextmanager
    def read_only():
        with original() as connection:

            def authorize(action, table, column, *_):
                if (
                    action == sqlite3.SQLITE_READ
                    and table == "session_events"
                    and column == "payload"
                ):
                    pytest.fail("read a historical source body")
                if action in {sqlite3.SQLITE_INSERT, sqlite3.SQLITE_UPDATE, sqlite3.SQLITE_DELETE}:
                    pytest.fail("GET wrote state")
                return sqlite3.SQLITE_OK

            connection.set_authorizer(authorize)
            yield connection

    monkeypatch.setattr(api.app.stores.tasks._database, "connect", read_only)
    # Local /usage intentionally retains its historical oracle. The cloud route
    # has separate native body-free SQL proof; attachment pages stay indexed here.
    for suffix in ("attachments",):
        response = api.handle(RouteRequest("GET", f"/tasks/{task.task_id}/{suffix}"))
        assert response.status_code == 200
        assert response.body["attachment_count"] == 1


@pytest.mark.parametrize("query", [{"limit": "257"}, {"max_bytes": "1048577"}, {"limit": "x"}])
def test_api_budget_bounds_are_explicit(tmp_path, query):
    store, task = summary_store(tmp_path)
    repair(store, task)
    response = adapter(store).handle(
        RouteRequest("GET", f"/tasks/{task.task_id}/attachments", query=query)
    )
    assert response.status_code == 400


def test_local_legacy_summary_keeps_oracle_and_never_repairs_in_get(tmp_path, monkeypatch):
    store, task = summary_store(tmp_path)
    append_attachment(store, task)
    repair(store, task)
    api = adapter(store)
    monkeypatch.setattr(
        api.app.stores.tasks, "backfill_read_summary", lambda *a: pytest.fail("repair")
    )
    response = api.handle(RouteRequest("GET", f"/tasks/{task.task_id}"))
    assert response.status_code == 200
    assert len(response.body["attachments"]) == 1


@pytest.mark.parametrize("payload", [None, {"input_tokens": 0, "resolved_model": "main"}])
def test_local_usage_endpoint_keeps_legacy_oracle_without_summary_preparation(
    tmp_path, monkeypatch, payload
):
    store, task = summary_store(tmp_path)
    if payload is not None:
        SQLiteEventStore(store._database.database_path).append(
            SessionEvent.create(
                session_id=task.active_segment_id,
                sequence=3,
                actor=EventActor.HARNESS,
                event_type=EventType.MODEL_RESPONSE_RECEIVED,
                payload=payload,
            )
        )
    oracle = summarize_task_model_usage(store.read_events(task.task_id, -1))
    api = adapter(store)
    for method in ("read_task_summary", "backfill_read_summary"):
        monkeypatch.setattr(api.app.stores.tasks, method, lambda *a: pytest.fail("summary repair"))
    response = api.handle(RouteRequest("GET", f"/tasks/{task.task_id}/usage"))
    assert response.status_code == 200
    assert response.body["model_usage"] == oracle
    assert "through_sequence" not in response.body
    assert store.read_task_summary(task.task_id).through_sequence == -1


def test_usage_projection_integrity_is_not_retryable_pending(tmp_path, monkeypatch):
    store, task = summary_store(tmp_path)

    def conflict(*args):
        raise CheckpointConflict("canonical source identity conflicts")

    monkeypatch.setattr(store, "read_task_summary", conflict)
    response = read_task_usage(store, task.task_id)
    assert response.status_code == 409
    assert response.body["code"] == "projection_integrity"
    assert response.body["retryable"] is False
