"""Original follow-up observation is never a second append or noncommit proof."""

import json
import sqlite3
from pathlib import Path
from types import SimpleNamespace
from uuid import uuid4

import pytest
from agent_core.ports.task_projection_checkpoints import CheckpointNotReady
from zebra_agent_api import RouteAdapter, RouteRequest, create_app
from zebra_agent_api.idempotency import request_hash
from zebra_agent_api.tenant_guard import tenant_scope_response

from tests.api.test_task_principal_guard import TASK_ID, _binding, _context, _verified
from tests.api.test_task_routes import _seed_completed


def _snapshot(database):
    with sqlite3.connect(database) as conn:
        return list(conn.iterdump())


def test_original_followup_after_restart_is_read_only(tmp_path: Path):
    database = tmp_path / "messages.sqlite"
    task = str(_seed_completed(database, tmp_path))
    adapter = RouteAdapter(create_app(database))
    body = {"role": "user", "content": "继续分析同一业务记录 😀"}
    key = str(uuid4())
    original = adapter.handle(
        RouteRequest("POST", f"/tasks/{task}/messages", body=body, headers={"Idempotency-Key": key})
    )
    assert original.status_code == 201 and original.body["rolled_over"]
    adapter = RouteAdapter(create_app(database))
    _ = adapter.app.stores  # Compose local SQLite adapters before the read-only request snapshot.
    before = _snapshot(database)
    for _ in range(3):
        receipt = adapter.handle(
            RouteRequest("GET", f"/tasks/{task}/messages/receipt", headers={"Idempotency-Key": key})
        )
        assert receipt.status_code == 200
        assert receipt.body == {
            "contract_version": 1,
            "status": "recorded",
            "task_id": task,
            "request_hash": request_hash(body),
            "response": {"status_code": original.status_code, "body": original.body},
        }
    assert _snapshot(database) == before
    missing = adapter.handle(
        RouteRequest(
            "GET", f"/tasks/{task}/messages/receipt", headers={"Idempotency-Key": str(uuid4())}
        )
    )
    assert missing.status_code == 200 and missing.body["status"] == "not_observed"
    assert missing.body["noncommit_proved"] is False
    assert _snapshot(database) == before


@pytest.mark.parametrize("key", [None, "", " ", "x" * 129, "bad\nkey"])
def test_invalid_key_does_not_read(key, monkeypatch, tmp_path):
    app = create_app(tmp_path / "keys.sqlite")

    def forbidden(**kwargs):
        pytest.fail("invalid key reached storage")

    monkeypatch.setattr(app.stores.idempotency, "get", forbidden)
    result = RouteAdapter(app).handle(
        RouteRequest(
            "GET",
            f"/tasks/{uuid4()}/messages/receipt",
            headers={} if key is None else {"Idempotency-Key": key},
        )
    )
    assert result.status_code == 400


def test_storage_failure_is_not_missing_or_success(monkeypatch, tmp_path):
    app = create_app(tmp_path / "failure.sqlite")

    def unavailable(**kwargs):
        raise RuntimeError("private connection detail")

    monkeypatch.setattr(app.stores.idempotency, "get", unavailable)
    result = RouteAdapter(app).handle(
        RouteRequest(
            "GET", f"/tasks/{uuid4()}/messages/receipt", headers={"Idempotency-Key": "original"}
        )
    )
    assert result.status_code == 503 and result.body["status"] == "unavailable"
    assert "private" not in json.dumps(result.body)


@pytest.mark.parametrize("case", ["owner", "other", "expired", "projection"])
def test_current_principal_gate_remains_authoritative(case):
    owner = _context("user-a")

    def load(_):
        if case == "projection":
            raise CheckpointNotReady("not caught up")
        return _binding(owner)

    app = SimpleNamespace(
        stores=SimpleNamespace(
            deployment_namespace="trench-prod",
            sessions=SimpleNamespace(
                get_session=lambda _: SimpleNamespace(namespace_id="trench-prod")
            ),
        ),
        settings=SimpleNamespace(database_url="postgresql://unused"),
        cloud_control=SimpleNamespace(deployment_namespace="trench-prod", load_task_binding=load),
    )
    context = _context("user-b") if case == "other" else owner
    if case == "expired":
        from datetime import UTC, datetime, timedelta

        context = context.model_copy(
            update={"expires_at": datetime.now(UTC) - timedelta(seconds=1)}
        )
    result = tenant_scope_response(
        app,
        RouteRequest(
            "GET",
            f"/tasks/{TASK_ID}/messages/receipt",
            headers={"Idempotency-Key": "original"},
            host_context=context,
            verified_host_grant=_verified(context),
        ),
    )
    if case == "owner":
        assert result is None
    else:
        assert result.status_code == {"other": 404, "expired": 403, "projection": 409}[case]
