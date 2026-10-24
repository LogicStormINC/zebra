"""Real PG surface effects, result and cooperative termination, never lease takeover."""

import os
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor
from threading import Event
from uuid import uuid4

import pytest
from agent_storage import apply_postgres_migrations, new_idempotency_record
from agent_storage.postgres.admission_atomic_surface import (
    CLAIM,
    RESULT,
    AtomicSurfaceAborted,
    atomic_surface_transaction,
    observe_atomic_termination,
    start_atomic_surface,
)
from agent_storage.postgres.client_control_leases import PostgresClientControlLeaseStore
from agent_storage.postgres.client_sessions import PostgresClientSessionRegistry
from agent_storage.postgres.idempotency import PostgresIdempotencyStore

from tests.agent_storage.test_client_surface_sync_postgres import mounted
from tests.agent_storage.test_postgres_migrations import isolated_migration_dsn as _isolated

isolated_migration_dsn = _isolated


def setup(dsn, protocol="atomic-surface/1"):
    apply_postgres_migrations(dsn)
    store = PostgresIdempotencyStore(dsn, deployment_namespace="atomic-tests")
    op = str(uuid4())
    store.save(
        new_idempotency_record(
            action=CLAIM,
            idempotency_key=op,
            request_hash="a" * 64,
            status_code=202,
            response_body={"kind": "surface_open", "dispatch_protocol": protocol},
        )
    )
    return store, op


def effects(store):
    db = store._database
    ports = (
        PostgresClientSessionRegistry(db._dsn, deployment_namespace=db.deployment_namespace),
        PostgresClientControlLeaseStore(db._dsn, deployment_namespace=db.deployment_namespace),
        db._dsn,
        db.deployment_namespace,
    )
    return mounted(ports)


def result(store, op):
    store.save(
        new_idempotency_record(
            action=RESULT,
            idempotency_key=op,
            request_hash="a" * 64,
            status_code=200,
            response_body={"status": "completed", "sealed_response": "test-adapter-only"},
        )
    )


def counts(store):
    with store._database.connect() as c:
        return [
            c.execute(
                f"SELECT count(*) AS n FROM {name} WHERE deployment_namespace=%s",
                (store._database.deployment_namespace,),
            ).fetchone()["n"]
            for name in ("client_sessions", "client_run_bindings", "client_control_leases")
        ]


def test_started_effects_stop_pending_then_rollback_proof(isolated_migration_dsn):
    store, op = setup(isolated_migration_dsn)
    assert start_atomic_surface(store, op, "a" * 64)
    ready, resume = Event(), Event()

    def run():
        with pytest.raises(AtomicSurfaceAborted):
            with atomic_surface_transaction(store, op, "a" * 64):
                effects(store)
                result(store, op)
                ready.set()
                assert resume.wait(5)

    with ThreadPoolExecutor(1) as pool:
        pending = pool.submit(run)
        assert ready.wait(5)
        assert counts(store) == [0, 0, 0]
        proof = observe_atomic_termination(store, op, "a" * 64, write=True)
        assert proof["state"] == "pending"
        resume.set()
        pending.result()
    assert counts(store) == [0, 0, 0]
    assert store.get(action=RESULT, idempotency_key=op) is None
    proof = observe_atomic_termination(store, op, "a" * 64, write=False)
    assert proof["state"] == "terminated" and proof["recorded_at"]
    assert not start_atomic_surface(store, op, "a" * 64)
    assert observe_atomic_termination(store, op, "a" * 64, write=False) == proof
    # Original stop and proof survive an independent process, with no effect replay.
    code = """import os
from agent_storage.postgres.idempotency import PostgresIdempotencyStore
from agent_storage.postgres.admission_atomic_surface import observe_atomic_termination
s=PostgresIdempotencyStore(os.environ["OWNED_DSN"],deployment_namespace="atomic-tests")
p=observe_atomic_termination(s,os.environ["OWNED_OP"],"a"*64,write=False)
assert p["state"]=="terminated"
"""
    subprocess.run(
        [sys.executable, "-c", code],
        env={**os.environ, "OWNED_DSN": isolated_migration_dsn, "OWNED_OP": op},
        check=True,
        timeout=10,
    )


def test_commit_first_receipt_and_effects_atomic_no_noncommit(isolated_migration_dsn):
    store, op = setup(isolated_migration_dsn)
    assert start_atomic_surface(store, op, "a" * 64)
    with atomic_surface_transaction(store, op, "a" * 64):
        session, snapshot, binding, profile = effects(store)
        result(store, op)
    assert counts(store) == [1, 1, 1]
    assert store.get(action=RESULT, idempotency_key=op) is not None
    assert observe_atomic_termination(store, op, "a" * 64, write=True)["state"] == "committed"
    assert counts(store) == [1, 1, 1]


def test_crash_rolls_back_but_absence_alone_not_proof(isolated_migration_dsn):
    store, op = setup(isolated_migration_dsn)
    assert start_atomic_surface(store, op, "a" * 64)
    with pytest.raises(RuntimeError):
        with atomic_surface_transaction(store, op, "a" * 64):
            effects(store)
            raise RuntimeError("owned crash before receipt")
    assert counts(store) == [0, 0, 0]
    assert observe_atomic_termination(store, op, "a" * 64, write=False)["state"] == "unresolved"
    assert observe_atomic_termination(store, op, "a" * 64, write=True)["state"] == "terminated"


@pytest.mark.parametrize("protocol", ["", "pre-dispatch/1"])
def test_old_started_and_partial_claim_never_upgraded(isolated_migration_dsn, protocol):
    store, op = setup(isolated_migration_dsn, protocol)
    assert observe_atomic_termination(store, op, "a" * 64, write=True)["state"] == "unsupported"
    assert (
        observe_atomic_termination(store, str(uuid4()), "a" * 64, write=True)["state"]
        == "not_observed"
    )


def test_process_exit_rolls_back_before_positive_proof(isolated_migration_dsn):
    from time import sleep

    store, op = setup(isolated_migration_dsn)
    assert start_atomic_surface(store, op, "a" * 64)
    code = """import os
from agent_storage.postgres.idempotency import PostgresIdempotencyStore
from agent_storage.postgres.admission_atomic_surface import atomic_surface_transaction
from tests.agent_storage.test_admission_atomic_surface import effects
s=PostgresIdempotencyStore(os.environ["OWNED_DSN"],deployment_namespace="atomic-tests")
with atomic_surface_transaction(s,os.environ["OWNED_OP"],"a"*64):
    effects(s)
    os._exit(17)
"""
    child = subprocess.run(
        [sys.executable, "-c", code],
        env={
            **os.environ,
            "OWNED_DSN": isolated_migration_dsn,
            "OWNED_OP": op,
        },
        timeout=10,
    )
    assert child.returncode == 17
    proof = observe_atomic_termination(store, op, "a" * 64, write=True)
    for _ in range(20):
        if proof["state"] != "pending":
            break
        sleep(0.05)
        proof = observe_atomic_termination(store, op, "a" * 64, write=False)
    assert proof["state"] == "terminated"
    assert counts(store) == [0, 0, 0]
    assert store.get(action=RESULT, idempotency_key=op) is None


@pytest.mark.parametrize("status", [201, 409, "receipt_loss"])
def test_atomic_api_receipt_and_effects_commit_together(
    isolated_migration_dsn, monkeypatch, status
):
    import base64
    from types import SimpleNamespace

    from agent_storage.postgres.client_capabilities import PostgresClientCapabilityRegistry
    from cryptography.hazmat.primitives.ciphers.aead import AESGCM
    from zebra_agent_api import client_admission_operations as api
    from zebra_agent_api.responses import ApiResponse
    from zebra_agent_api.routes import RouteRequest

    store, unused = setup(isolated_migration_dsn)
    db = store._database
    app = SimpleNamespace(
        stores=SimpleNamespace(idempotency=store),
        client_platform=SimpleNamespace(
            client_sessions=PostgresClientSessionRegistry(
                db._dsn, deployment_namespace=db.deployment_namespace
            ),
            client_control_leases=PostgresClientControlLeaseStore(
                db._dsn, deployment_namespace=db.deployment_namespace
            ),
            frontend_capabilities=PostgresClientCapabilityRegistry(
                db._dsn, deployment_namespace=db.deployment_namespace
            ),
        ),
    )
    monkeypatch.setattr(api, "_authorize", lambda *a: None)

    def dispatch(*args):
        effects(store)
        return ApiResponse(
            201 if status == "receipt_loss" else status,
            {"session_credential": "owned-never-plaintext"},
        )

    monkeypatch.setattr(api, "_dispatch", dispatch)
    op = str(uuid4())
    key = bytes(range(32))
    request = RouteRequest(
        "POST",
        f"/v1/admission-operations/{op}",
        headers={"X-Zebra-Admission-Protocol": "atomic-surface/1"},
        body={"kind": "surface_open", "task": str(uuid4()), "run": "run-1", "payload": {}},
    )
    if status == "receipt_loss":
        save = store.save

        def lose(record):
            if record.action == RESULT:
                raise TimeoutError("owned receipt write failure")
            return save(record)

        monkeypatch.setattr(store, "save", lose)
        with pytest.raises(TimeoutError):
            api._handle(app, request, op, op, key)
        assert counts(store) == [0, 0, 0]
        assert store.get(action=RESULT, idempotency_key=op) is None
        assert (
            observe_atomic_termination(
                store, op, store.get(action=CLAIM, idempotency_key=op).request_hash, write=True
            )["state"]
            == "terminated"
        )
        return
    response = api._handle(app, request, op, op, key)
    assert counts(store) == ([1, 1, 1] if status == 201 else [0, 0, 0])
    if status == 201:
        assert response.body["status"] == "completed"
        raw = base64.b64decode(response.body["sealed_response"])
        assert b"owned-never-plaintext" in AESGCM(key).decrypt(
            raw[:12], raw[12:], response.body["request_hash"].encode()
        )
        assert "owned-never-plaintext" not in str(response.body)
    else:
        assert response.body["status"] == "unknown"
        assert store.get(action=RESULT, idempotency_key=op) is None
