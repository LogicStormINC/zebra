"""Real PG first-winner proof. Delayed handlers cannot dispatch after termination."""

import os
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from threading import Event

import pytest
from agent_storage import new_idempotency_record
from agent_storage.postgres.idempotency import PostgresIdempotencyStore
from zebra_agent_api import client_admission_operations as api
from zebra_agent_api.responses import ApiResponse

from tests.agent_storage.test_admission_operation_receipts import fixture
from tests.agent_storage.test_postgres_migrations import isolated_migration_dsn as _isolated

isolated_migration_dsn = _isolated


def original(app, request, op, key):
    claim = app.stores.idempotency.get(action=api._CLAIM, idempotency_key=op)
    return replace(
        request, method="POST", body=None, headers={"X-Zebra-Admission-Hash": claim.request_hash}
    )


def test_termination_wins_delayed_original_cannot_dispatch(isolated_migration_dsn, monkeypatch):
    app, request, op, key = fixture(isolated_migration_dsn, monkeypatch)
    request = replace(request, headers={"X-Zebra-Admission-Protocol": "pre-dispatch/1"})
    ready, resume = Event(), Event()
    store = app.stores.idempotency
    fence = store.admission_fence
    calls = []

    def pause(*args, terminate):
        if not terminate:
            ready.set()
            assert resume.wait(5)
        return fence(*args, terminate=terminate)

    monkeypatch.setattr(store, "admission_fence", pause)
    monkeypatch.setattr(api, "_dispatch", lambda *a: calls.append(1) or ApiResponse(201, {}))
    with ThreadPoolExecutor(2) as pool:
        pending = pool.submit(api._handle, app, request, op, op, key)
        assert ready.wait(5)
        read = original(app, request, op, key)
        proof = api._handle(app, read, op, op, key, termination=True)
        assert proof.body["non_commit_proven"] is True
        assert proof.body["state"] == "terminated"
        resume.set()
        assert pending.result().body["status"] == "unknown"
    assert calls == []
    assert store.get(action=api._RESULT, idempotency_key=op) is None
    # An independent process and restarted adapter must observe the same irreversible fence.
    claim = store.get(action=api._CLAIM, idempotency_key=op)
    env = {
        **os.environ,
        "OWNED_ADMISSION_DSN": isolated_migration_dsn,
        "OWNED_OP": op,
        "OWNED_HASH": claim.request_hash,
    }
    code = """import os
from agent_storage.postgres.idempotency import PostgresIdempotencyStore
s=PostgresIdempotencyStore(os.environ["OWNED_ADMISSION_DSN"],deployment_namespace="admission-op")
v=s.admission_fence(os.environ["OWNED_OP"],os.environ["OWNED_HASH"],terminate=False)
assert v["state"]=="terminated"
"""
    subprocess.run([sys.executable, "-c", code], env=env, check=True, timeout=10)
    for method in ("POST", "GET"):
        again = api._handle(app, replace(read, method=method), op, op, key, termination=True)
        assert again == proof
        assert again.body["retry_allowed"] is False
        assert again.body["controller_reclaim_allowed"] is False
    assert api._handle(app, request, op, op, key).body["status"] == "unknown"
    wrong = replace(read, headers={"X-Zebra-Admission-Hash": "0" * 64})
    assert api._handle(app, wrong, op, op, key, termination=True).status_code == 409
    monkeypatch.setattr(api, "_authorize", lambda *a: ApiResponse(403, {"status": "denied"}))
    assert api._handle(app, read, op, op, key, termination=True).status_code == 403
    assert calls == []


def test_started_partial_dispatch_never_proves_noncommit(isolated_migration_dsn, monkeypatch):
    app, request, op, key = fixture(isolated_migration_dsn, monkeypatch)
    request = replace(request, headers={"X-Zebra-Admission-Protocol": "pre-dispatch/1"})

    def crash(*args):
        raise RuntimeError("possible committed effects")

    monkeypatch.setattr(api, "_dispatch", crash)
    with pytest.raises(RuntimeError):
        api._handle(app, request, op, op, key)
    read = original(app, request, op, key)
    for _ in range(2):
        result = api._handle(app, read, op, op, key, termination=True)
        assert result.body["state"] == "started"
        assert result.body["non_commit_proven"] is False
    assert api._handle(app, request, op, op, key).body["status"] == "unknown"


def test_legacy_and_absent_claims_are_not_proof(isolated_migration_dsn, monkeypatch):
    app, request, op, key = fixture(isolated_migration_dsn, monkeypatch)
    read = replace(request, method="GET", body=None, headers={"X-Zebra-Admission-Hash": "a" * 64})
    monkeypatch.setattr(api, "host_list_context_response", lambda *a: None)
    # No claim is not a tombstone: a delayed original could still arrive.
    assert api._handle(app, read, op, op, key, termination=True).body["state"] == "not_observed"
    monkeypatch.setattr(api, "_dispatch", lambda *a: ApiResponse(201, {}))
    api._handle(app, request, op, op, key)
    result = api._handle(app, original(app, request, op, key), op, op, key, termination=True)
    assert result.body["state"] == "unsupported"
    assert result.body["non_commit_proven"] is False


def test_start_terminate_race_has_one_irreversible_winner(isolated_migration_dsn, monkeypatch):
    app, request, op, key = fixture(isolated_migration_dsn, monkeypatch)
    store = app.stores.idempotency
    store.save(
        new_idempotency_record(
            action=api._CLAIM,
            idempotency_key=op,
            request_hash="a" * 64,
            status_code=202,
            response_body={"dispatch_protocol": "pre-dispatch/1"},
        )
    )
    other = PostgresIdempotencyStore(isolated_migration_dsn, deployment_namespace="admission-op")
    with ThreadPoolExecutor(2) as pool:
        start = pool.submit(store.admission_fence, op, "a" * 64, terminate=False)
        stop = pool.submit(other.admission_fence, op, "a" * 64, terminate=True)
        assert start.result() == stop.result()
    state = start.result()
    assert state["state"] in {"started", "terminated"}
    assert store.admission_fence(op, "a" * 64, terminate=True) == state
    assert other.admission_fence(op, "a" * 64, terminate=False) == state
