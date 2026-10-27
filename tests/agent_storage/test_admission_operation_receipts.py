"""Real shared PG original claim/result; dispatch stub isolates journal invariants."""

import base64
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from types import SimpleNamespace
from uuid import uuid4

import pytest
from agent_storage import apply_postgres_migrations
from agent_storage.postgres.idempotency import PostgresIdempotencyStore
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from zebra_agent_api import client_admission_operations as api
from zebra_agent_api.responses import ApiResponse
from zebra_agent_api.routes import RouteRequest

from tests.agent_storage.test_postgres_migrations import isolated_migration_dsn as _isolated

isolated_migration_dsn = _isolated


def fixture(dsn, monkeypatch):
    apply_postgres_migrations(dsn)
    app = SimpleNamespace(
        stores=SimpleNamespace(
            idempotency=PostgresIdempotencyStore(dsn, deployment_namespace="admission-op")
        )
    )
    monkeypatch.setattr(api, "_authorize", lambda *a: None)
    key = bytes(range(32))
    op = str(uuid4())
    request = RouteRequest(
        "POST",
        f"/v1/admission-operations/{op}",
        body={
            "kind": "task_create",
            "task": "",
            "run": "",
            "payload": {"execute": False},
        },
    )
    return app, request, op, key


def test_shared_claim_only_one_dispatch_and_sealed_exact_original(
    isolated_migration_dsn, monkeypatch
):
    app, request, op, key = fixture(isolated_migration_dsn, monkeypatch)
    calls = []
    monkeypatch.setattr(
        api,
        "_dispatch",
        lambda *a: calls.append(1)
        or ApiResponse(201, {"task_id": "original", "session_credential": "never-plaintext"}),
    )
    with ThreadPoolExecutor(2) as pool:
        results = list(pool.map(lambda _: api._handle(app, request, op, op, key), range(2)))
    assert len(calls) == 1
    receipt = next(r for r in results if r.body["status"] == "completed")
    read = replace(
        request,
        method="GET",
        body=None,
        headers={
            "X-Zebra-Admission-Hash": receipt.body["request_hash"],
        },
    )
    assert api._handle(app, read, op, op, key) == receipt
    assert api._handle(app, read, op, op, key) == receipt
    assert len(calls) == 1
    sealed = base64.b64decode(receipt.body["sealed_response"])
    raw = AESGCM(key).decrypt(sealed[:12], sealed[12:], receipt.body["request_hash"].encode())
    assert b"never-plaintext" in raw
    assert "never-plaintext" not in str(receipt.body)
    denied = api._handle(app, read, op, op, bytes(reversed(key)))
    assert denied.status_code == 409
    changed = replace(
        request, body={**request.body, "payload": {"execute": False, "prompt": "other"}}
    )
    assert api._handle(app, changed, op, op, key).status_code == 409


def test_crash_after_effect_never_reclaims_or_dispatches(isolated_migration_dsn, monkeypatch):
    app, request, op, key = fixture(isolated_migration_dsn, monkeypatch)
    calls = []

    def crash(*args):
        calls.append(1)
        raise RuntimeError("owned crash after possible native effect")

    monkeypatch.setattr(api, "_dispatch", crash)
    with pytest.raises(RuntimeError):
        api._handle(app, request, op, op, key)
    for _ in range(3):
        observed = api._handle(app, request, op, op, key)
        assert observed.body["status"] == "unknown"
    assert len(calls) == 1


def test_missing_result_observation_is_read_only_and_cannot_prove_no_effect(
    isolated_migration_dsn, monkeypatch
):
    app, request, op, key = fixture(isolated_migration_dsn, monkeypatch)
    calls = []

    def crash(*args):
        calls.append(1)
        raise RuntimeError("possible partial commit")

    monkeypatch.setattr(api, "_dispatch", crash)
    with pytest.raises(RuntimeError):
        api._handle(app, request, op, op, key)
    claim = app.stores.idempotency.get(action=api._CLAIM, idempotency_key=op)
    read = replace(
        request,
        method="GET",
        body=None,
        headers={
            "X-Zebra-Admission-Hash": claim.request_hash,
        },
    )
    for _ in range(2):
        observed = api._handle(app, read, op, op, key, observation=True)
        assert observed.status_code == 200
        assert observed.body["claim_recorded"] is True
        assert observed.body["result_recorded"] is False
        assert observed.body["partial_commit_possible"] is True
        assert observed.body["retry_allowed"] is False
        assert observed.body["controller_reclaim_allowed"] is False
        assert observed.body["request_hash"] == claim.request_hash
        assert "sealed_response" not in observed.body
    assert calls == [1]
    assert app.stores.idempotency.get(action=api._RESULT, idempotency_key=op) is None
    wrong = replace(read, headers={"X-Zebra-Admission-Hash": "0" * 64})
    assert api._handle(app, wrong, op, op, key, observation=True).status_code == 409
