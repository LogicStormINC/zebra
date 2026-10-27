"""Owned real PG: exact receipt/rollback/concurrent replicas; no authority stub claim."""

from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from types import SimpleNamespace
from uuid import uuid4

from agent_storage import (
    PostgresAgentTaskStore,
    PostgresEventStore,
    PostgresProjectionStore,
    PostgresWorkspaceProjectionStore,
    SQLiteEventStore,
    apply_postgres_migrations,
    bootstrap_control_plane_epoch,
    sqlite_control_plane_stores,
)
from zebra_agent_api import client_approval_operations as api
from zebra_agent_api.routes import RouteRequest

from tests.agent_storage.test_postgres_migrations import isolated_migration_dsn as _isolated
from tests.api.test_approval_routes import _seed_waiting_session

isolated_migration_dsn = _isolated


def fixture(dsn, tmp_path, monkeypatch):
    apply_postgres_migrations(dsn)
    bootstrap_control_plane_epoch(dsn, deployment_namespace="approval-op")
    db = tmp_path / "seed.sqlite"
    seed = _seed_waiting_session(db)
    stores = replace(
        sqlite_control_plane_stores(db),
        events=PostgresEventStore(dsn, deployment_namespace="approval-op"),
        sessions=PostgresProjectionStore(dsn, deployment_namespace="approval-op"),
        workspaces=PostgresWorkspaceProjectionStore(dsn, deployment_namespace="approval-op"),
        tasks=PostgresAgentTaskStore(dsn, deployment_namespace="approval-op"),
    )
    for event in SQLiteEventStore(db).list_for_session(seed.session_id):
        stores.events.append(event)
    stores.sessions.save_session(seed)
    task = stores.tasks.ensure_for_session(seed.session_id)
    client = uuid4()
    monkeypatch.setattr(api, "_current", lambda *a: SimpleNamespace(client_session_id=client))
    app = SimpleNamespace(stores=stores)
    path = f"/v1/tasks/{task.task_id}/runs/run-1/approval-operations/{uuid4()}"
    headers = {"X-Zebra-Command-Segment": str(seed.session_id)}
    body = {
        "decision": "approve",
        "operator": "user",
        "reason": "explicit",
        "expected_revision": seed.current_sequence,
    }
    return app, RouteRequest("POST", path, headers=headers, body=body), seed


def test_two_replicas_recover_one_original_without_projection_or_wakeup_duplication(
    isolated_migration_dsn, tmp_path, monkeypatch
):
    app, request, seed = fixture(isolated_migration_dsn, tmp_path, monkeypatch)
    with ThreadPoolExecutor(2) as pool:
        responses = list(
            pool.map(lambda _: api.handle_client_approval_operation(app, request), range(2))
        )
    assert all(r.status_code == 200 for r in responses), responses
    assert responses[0].body == responses[1].body
    before = app.stores.events.list_for_session(seed.session_id)
    assert len(before) == seed.current_sequence + 3
    receipt = api.handle_client_approval_operation(app, replace(request, method="GET", body=None))
    assert receipt.body == responses[0].body
    assert app.stores.events.list_for_session(seed.session_id) == before
    changed = api.handle_client_approval_operation(
        app, replace(request, body={**request.body, "decision": "reject"})
    )
    assert changed.status_code == 409
    assert app.stores.events.list_for_session(seed.session_id) == before


def test_failed_continuation_rolls_back_decision_and_projection(
    isolated_migration_dsn, tmp_path, monkeypatch
):
    app, request, seed = fixture(isolated_migration_dsn, tmp_path, monkeypatch)
    before = app.stores.events.list_for_session(seed.session_id)
    original = app.stores.events.append

    def fail_wakeup(event):
        if event.idempotency_key.startswith("approval-resume:"):
            raise RuntimeError("owned crash before wake commit")
        return original(event)

    monkeypatch.setattr(app.stores.events, "append", fail_wakeup)
    response = api.handle_client_approval_operation(app, request)
    assert response.status_code == 503
    assert app.stores.events.list_for_session(seed.session_id) == before
    assert app.stores.sessions.get_session(seed.session_id) == seed
    observed = api.handle_client_approval_operation(app, replace(request, method="GET", body=None))
    assert observed.body == {"status": "not_observed"}


def test_reject_is_atomic_and_never_reads_full_history(
    isolated_migration_dsn, tmp_path, monkeypatch
):
    app, request, seed = fixture(isolated_migration_dsn, tmp_path, monkeypatch)
    before = app.stores.events.list_for_session(seed.session_id)
    with monkeypatch.context() as guard:

        def forbidden(*args):
            raise AssertionError("approval may not load historical event bodies")

        guard.setattr(app.stores.events, "list_for_session", forbidden)
        rejected = api.handle_client_approval_operation(
            app, replace(request, body={**request.body, "decision": "reject"})
        )
        assert rejected.status_code == 200, rejected
        original = api.handle_client_approval_operation(
            app, replace(request, method="GET", body=None)
        )
        assert original.body == rejected.body
    after = app.stores.events.list_for_session(seed.session_id)
    assert after[:-1] == before
    assert after[-1].event_type.value == "approval_rejected"
    assert rejected.body["decision"] == "reject"
