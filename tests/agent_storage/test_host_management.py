from __future__ import annotations

import multiprocessing
import subprocess
import time
from collections.abc import Iterator
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import psycopg
import pytest
from agent_storage import HostGrantAttempt, apply_postgres_migrations
from agent_storage.postgres.host_auth import HostRegistryRecord, PostgresHostAuthorityStore
from agent_storage.postgres.host_management import (
    HostManagementConflict,
    HostManagementExpired,
    HostManagementStore,
    HostManagementTrust,
    HostManagementUnavailable,
)
from psycopg.conninfo import make_conninfo


@pytest.fixture(scope="module")
def host_management_dsn() -> Iterator[str]:
    """Always own the server; never accept an existing service DSN."""
    name = f"zebra-host-management-{uuid4().hex[:12]}"
    subprocess.run(
        [
            "docker",
            "run",
            "--rm",
            "-d",
            "--name",
            name,
            "-e",
            "POSTGRES_PASSWORD=disposable",
            "-p",
            "127.0.0.1::5432",
            "postgres:17-alpine",
        ],
        check=True,
        capture_output=True,
        text=True,
    )
    try:
        port = subprocess.check_output(
            [
                "docker",
                "inspect",
                "--format",
                '{{(index (index .NetworkSettings.Ports "5432/tcp") 0).HostPort}}',
                name,
            ],
            text=True,
        ).strip()
        dsn = make_conninfo(
            host="127.0.0.1", port=port, dbname="postgres", user="postgres", password="disposable"
        )
        until = time.monotonic() + 30
        while True:
            try:
                with psycopg.connect(dsn):
                    break
            except psycopg.OperationalError:
                if time.monotonic() >= until:
                    raise
                time.sleep(0.1)
        apply_postgres_migrations(dsn)
        yield dsn
    finally:
        subprocess.run(["docker", "rm", "-f", name], check=True, capture_output=True)


@pytest.fixture
def store(host_management_dsn: str) -> HostManagementStore:
    return HostManagementStore(host_management_dsn, deployment_namespace=f"test-{uuid4()}")


def trust(**changes: object) -> HostManagementTrust:
    value = HostManagementTrust(
        deployment_id="runtime-a",
        audience="management-a",
        product_id="product-a",
        environment="test",
        host_app_id="example",
        namespace_id="tenant-a",
        revision=1,
        fingerprint="a" * 64,
        expires_at=datetime.now(UTC) + timedelta(minutes=5),
    )
    return replace(value, **changes)


def registry(**changes: object) -> HostRegistryRecord:
    value = HostRegistryRecord(
        host_app_id="example",
        namespace_id="tenant-a",
        issuer="https://idp.example",
        audience="runtime-a",
        jwks_uri="https://idp.example/keys",
        allowed_origins=("https://example.com",),
        algorithms=("RS256",),
        policy_version="v1",
    )
    return replace(value, **changes)


def test_missing_approval_and_initial_cas_replay(store: HostManagementStore) -> None:
    t, r, operation = trust(), registry(), str(uuid4())
    with pytest.raises(HostManagementUnavailable):
        store.read(t)
    store.approve(t, expected_revision=0)
    assert store.read(t).record is None
    result = store.apply(t, r, expected_revision=0, operation_id=operation)
    assert (result.record, result.revision, result.replayed) == (r, 1, False)
    replay = store.apply(t, r, expected_revision=0, operation_id=operation)
    assert (replay.record, replay.revision, replay.replayed) == (r, 1, True)
    with pytest.raises(HostManagementConflict):
        store.apply(t, replace(r, active=False), expected_revision=0, operation_id=operation)
    with pytest.raises(HostManagementConflict):
        store.apply(t, r, expected_revision=0, operation_id=str(uuid4()))
    store.apply(t, replace(r, active=False), expected_revision=1, operation_id=str(uuid4()))
    assert store.read(t).revision == 2
    assert store.apply(t, r, expected_revision=0, operation_id=operation).record == r


def test_current_approval_fences_receipts_and_scope(store: HostManagementStore) -> None:
    t, r, operation = trust(), registry(), str(uuid4())
    store.approve(t, expected_revision=0)
    store.apply(t, r, expected_revision=0, operation_id=operation)
    newer = replace(t, revision=2, fingerprint="b" * 64)
    store.approve(newer, expected_revision=1)
    for action in (
        lambda: store.read(t),
        lambda: store.apply(
            t,
            r,
            expected_revision=0,
            operation_id=operation,
        ),
    ):
        with pytest.raises(HostManagementUnavailable):
            action()
    assert store.read(newer).revision == 1
    with pytest.raises(HostManagementUnavailable):
        store.read(replace(newer, product_id="other"))
    with pytest.raises(HostManagementConflict):
        store.approve(replace(newer, revision=3, product_id="other"), expected_revision=2)
    with pytest.raises(HostManagementConflict):
        store.approve(newer, expected_revision=1)
    # Empty-action revocation is a new fingerprint at the storage boundary.
    revoked = replace(newer, revision=3, fingerprint="c" * 64)
    store.approve(revoked, expected_revision=2)
    with pytest.raises(HostManagementUnavailable):
        store.read(newer)


def test_legacy_revision_and_inactive_grants(
    store: HostManagementStore, host_management_dsn: str
) -> None:
    t, r = trust(), registry()
    store.approve(t, expected_revision=0)
    legacy = PostgresHostAuthorityStore(
        host_management_dsn, deployment_namespace=store.deployment_namespace
    )
    legacy.upsert_registry(r)
    assert store.read(t).revision == 1
    legacy.upsert_registry(r)
    assert store.read(t).revision == 2
    with pytest.raises(HostManagementConflict):
        store.apply(t, r, expected_revision=1, operation_id=str(uuid4()))
    store.apply(t, replace(r, active=False), expected_revision=2, operation_id=str(uuid4()))
    attempt = HostGrantAttempt(
        issuer=r.issuer,
        jti="one",
        host_app_id=r.host_app_id,
        namespace_id=r.namespace_id,
        algorithm="RS256",
        grant_digest="a" * 64,
        scopes_digest="b" * 64,
        resource_digest="c" * 64,
        expires_at=datetime.now(UTC) + timedelta(minutes=1),
    )
    assert legacy.consume_grant(attempt).outcome == "rejected"
    legacy.upsert_registry(r)
    assert store.read(t).revision == 4
    assert legacy.consume_grant(attempt).accepted


def _race(
    dsn: str, namespace: str, t: HostManagementTrust, start: object, results: object, operation: str
) -> None:
    start.wait()  # type: ignore[attr-defined]
    try:
        value = HostManagementStore(dsn, deployment_namespace=namespace).apply(
            t,
            registry(),
            expected_revision=0,
            operation_id=operation,
        )
        results.put(("ok", value.revision, value.replayed))  # type: ignore[attr-defined]
    except HostManagementConflict:
        results.put(("conflict",))  # type: ignore[attr-defined]


@pytest.mark.parametrize("identical", [False, True])
def test_independent_process_competition(
    store: HostManagementStore, host_management_dsn: str, identical: bool
) -> None:
    t, operation = trust(), str(uuid4())
    store.approve(t, expected_revision=0)
    context = multiprocessing.get_context("spawn")
    start, results = context.Event(), context.Queue()
    processes = [
        context.Process(
            target=_race,
            args=(
                host_management_dsn,
                store.deployment_namespace,
                t,
                start,
                results,
                operation if identical else str(uuid4()),
            ),
        )
        for _ in range(2)
    ]
    for child in processes:
        child.start()
    start.set()
    outcomes = [results.get(timeout=20) for _ in processes]
    for child in processes:
        child.join(timeout=20)
        assert child.exitcode == 0
    assert store.read(t).revision == 1
    if identical:
        assert sorted(outcomes) == [("ok", 1, False), ("ok", 1, True)]
    else:
        assert sorted(outcomes) == [("conflict",), ("ok", 1, False)]


def test_expiry_waiting_on_registry_rolls_back(
    store: HostManagementStore, host_management_dsn: str
) -> None:
    t, r = trust(expires_at=datetime.now(UTC) + timedelta(seconds=0.9)), registry()
    store.approve(t, expected_revision=0)
    store.apply(t, r, expected_revision=0, operation_id=str(uuid4()))
    with psycopg.connect(host_management_dsn) as blocker:
        blocker.execute(
            "SELECT 1 FROM host_authority_registries WHERE deployment_namespace=%s FOR UPDATE",
            (store.deployment_namespace,),
        )
        with ThreadPoolExecutor(max_workers=1) as executor:
            pending = executor.submit(
                store.apply,
                t,
                replace(r, active=False),
                expected_revision=1,
                operation_id=str(uuid4()),
            )
            time.sleep(1)
            blocker.commit()
            with pytest.raises(
                (
                    HostManagementExpired,
                    TimeoutError,
                    psycopg.errors.QueryCanceled,
                    psycopg.errors.LockNotAvailable,
                )
            ):
                pending.result(timeout=3)
    fresh = replace(
        t, revision=2, fingerprint="b" * 64, expires_at=datetime.now(UTC) + timedelta(minutes=1)
    )
    store.approve(fresh, expected_revision=1)
    assert store.read(fresh).record == r
    assert store.read(fresh).revision == 1
    with psycopg.connect(host_management_dsn) as connection:
        assert connection.execute(
            "SELECT count(*) FROM host_management_receipts WHERE deployment_namespace=%s",
            (store.deployment_namespace,),
        ).fetchone() == (1,)


def test_other_binding_does_not_wait_on_approval_lock(
    store: HostManagementStore, host_management_dsn: str
) -> None:
    first, second = trust(), trust(host_app_id="second")
    store.approve(first, expected_revision=0)
    store.approve(second, expected_revision=0)
    with psycopg.connect(host_management_dsn) as blocker:
        blocker.execute(
            "SELECT 1 FROM host_management_approvals "
            "WHERE deployment_namespace=%s AND host_app_id=%s FOR UPDATE",
            (store.deployment_namespace, first.host_app_id),
        )
        assert store.read(second).revision == 0


def test_atomic_receipt_audit_and_approval_cas(
    store: HostManagementStore, host_management_dsn: str
) -> None:
    t = trust()
    with ThreadPoolExecutor(max_workers=2) as executor:

        def approve() -> str:
            try:
                store.approve(t, expected_revision=0)
                return "approved"
            except HostManagementConflict:
                return "conflict"

        assert sorted(executor.map(lambda _: approve(), range(2))) == ["approved", "conflict"]
    operation = str(uuid4())
    store.apply(t, registry(), expected_revision=0, operation_id=operation)
    store.apply(t, registry(), expected_revision=0, operation_id=operation)
    with psycopg.connect(host_management_dsn) as connection:
        assert connection.execute(
            "SELECT count(*) FROM host_management_audit WHERE deployment_namespace=%s",
            (store.deployment_namespace,),
        ).fetchone() == (2,)
        assert connection.execute(
            "SELECT count(*) FROM host_management_receipts WHERE deployment_namespace=%s",
            (store.deployment_namespace,),
        ).fetchone() == (1,)


@pytest.mark.parametrize(
    "changes",
    [
        {"revision": True},
        {"revision": 0},
        {"fingerprint": "secret"},
        {"expires_at": datetime(2026, 1, 1)},
        {"host_app_id": " x "},
    ],
)
def test_trust_input_validation(changes: dict[str, object]) -> None:
    with pytest.raises(ValueError):
        trust(**changes)


def test_failed_audit_rolls_back_registry_and_receipt(
    store: HostManagementStore,
    host_management_dsn: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    t = trust()
    store.approve(t, expected_revision=0)

    def fail_audit(connection: object, *args: object) -> None:
        connection.execute("SELECT 1/0")  # type: ignore[attr-defined]

    monkeypatch.setattr(store, "_audit", fail_audit)
    with pytest.raises(psycopg.errors.DivisionByZero):
        store.apply(t, registry(), expected_revision=0, operation_id=str(uuid4()))
    assert store.read(t).record is None
    with psycopg.connect(host_management_dsn) as connection:
        assert connection.execute(
            "SELECT count(*) FROM host_management_receipts WHERE deployment_namespace=%s",
            (store.deployment_namespace,),
        ).fetchone() == (0,)
        assert connection.execute(
            "SELECT count(*) FROM host_management_audit WHERE deployment_namespace=%s",
            (store.deployment_namespace,),
        ).fetchone() == (1,)


def test_rotation_waits_for_inflight_apply_without_lock_inversion(
    store: HostManagementStore,
    host_management_dsn: str,
) -> None:
    t, r = trust(), registry()
    store.approve(t, expected_revision=0)
    store.apply(t, r, expected_revision=0, operation_id=str(uuid4()))
    newer = replace(t, revision=2, fingerprint="b" * 64)
    with psycopg.connect(host_management_dsn) as blocker:
        blocker.execute(
            "SELECT 1 FROM host_authority_registries WHERE deployment_namespace=%s FOR UPDATE",
            (store.deployment_namespace,),
        )
        with ThreadPoolExecutor(max_workers=2) as executor:
            apply = executor.submit(
                store.apply,
                t,
                replace(r, active=False),
                expected_revision=1,
                operation_id=str(uuid4()),
            )
            # Wait for native row lock, not an assumed thread scheduling delay.
            until = time.monotonic() + 1
            while True:
                with psycopg.connect(host_management_dsn) as observer:
                    waiting = observer.execute(
                        "SELECT count(*) FROM pg_stat_activity WHERE wait_event_type='Lock' "
                        "AND query LIKE 'SELECT * FROM host_authority_registries%'",
                    ).fetchone()
                if waiting and waiting[0]:
                    break
                assert time.monotonic() < until
                time.sleep(0.01)
            approval = executor.submit(store.approve, newer, expected_revision=1)
            time.sleep(0.05)
            assert not approval.done()
            blocker.commit()
            assert apply.result(timeout=3).revision == 2
            approval.result(timeout=3)
    with pytest.raises(HostManagementUnavailable):
        store.read(t)
    assert store.read(newer).record == replace(r, active=False)


def test_legacy_writer_wins_before_api_cas(
    store: HostManagementStore,
    host_management_dsn: str,
) -> None:
    t, r = trust(), registry()
    store.approve(t, expected_revision=0)
    store.apply(t, r, expected_revision=0, operation_id=str(uuid4()))
    with psycopg.connect(host_management_dsn) as writer:
        writer.execute(
            "UPDATE host_authority_registries SET revision=revision+1 "
            "WHERE deployment_namespace=%s",
            (store.deployment_namespace,),
        )
        with ThreadPoolExecutor(max_workers=1) as executor:
            apply = executor.submit(
                store.apply,
                t,
                replace(r, active=False),
                expected_revision=1,
                operation_id=str(uuid4()),
            )
            time.sleep(0.05)
            writer.commit()
            with pytest.raises(HostManagementConflict):
                apply.result(timeout=3)
    assert store.read(t).record == r
    assert store.read(t).revision == 2


def test_expired_trust_and_invalid_apply_inputs(store: HostManagementStore) -> None:
    t = trust()
    store.approve(t, expected_revision=0)
    with pytest.raises(HostManagementExpired):
        store.read(replace(t, expires_at=datetime.now(UTC) - timedelta(seconds=1)))
    for revision in (True, -1, 2**53 - 1):
        with pytest.raises(ValueError):
            store.apply(t, registry(), expected_revision=revision, operation_id=str(uuid4()))
    for operation in ("invalid", str(uuid4()).upper()):
        with pytest.raises(ValueError):
            store.apply(t, registry(), expected_revision=0, operation_id=operation)
    with pytest.raises(HostManagementUnavailable):
        store.apply(
            t, registry(namespace_id="another"), expected_revision=0, operation_id=str(uuid4())
        )
