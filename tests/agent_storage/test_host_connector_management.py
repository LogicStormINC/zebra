"""Storage acceptance always owns a fresh disposable PostgreSQL; no optional DSN."""

from __future__ import annotations

import json
import multiprocessing
import subprocess
import time
from collections.abc import Iterator
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import uuid4

import psycopg
import pytest
from agent_core.domain.host_connectors import HostConnectorBinding, HostConnectorProfileVersion
from agent_storage import apply_postgres_migrations
from agent_storage.postgres.host_auth import HostRegistryRecord
from agent_storage.postgres.host_connector_management import HostConnectorManagementStore
from agent_storage.postgres.host_connectors import PostgresHostConnectorRegistry
from agent_storage.postgres.host_management import (
    HostManagementConflict,
    HostManagementExpired,
    HostManagementStore,
    HostManagementTrust,
    HostManagementUnavailable,
)
from agent_storage.postgres.host_manifest_freeze import store_frozen_manifest
from psycopg import sql
from psycopg.conninfo import make_conninfo


@pytest.fixture(scope="module")
def connector_dsn() -> Iterator[str]:
    name = f"zebra-connector-management-{uuid4().hex[:12]}"
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
        subprocess.run(["docker", "rm", "-fv", name], check=True, capture_output=True)


@pytest.fixture
def managed(
    connector_dsn: str,
) -> tuple[
    HostConnectorManagementStore,
    PostgresHostConnectorRegistry,
    HostManagementStore,
    HostManagementTrust,
]:
    namespace = f"connector-{uuid4()}"
    management = HostManagementStore(connector_dsn, deployment_namespace=namespace)
    trust = HostManagementTrust(
        "deployment",
        "audience",
        "product",
        "test",
        "example",
        "tenant-a",
        1,
        "a" * 64,
        datetime.now(UTC) + timedelta(minutes=5),
    )
    management.approve(trust, 0)
    return (
        HostConnectorManagementStore(connector_dsn, deployment_namespace=namespace),
        PostgresHostConnectorRegistry(connector_dsn, deployment_namespace=namespace),
        management,
        trust,
    )


def profile(**changes: Any) -> HostConnectorProfileVersion:
    return HostConnectorProfileVersion(
        host_app_id="example",
        connector_id="main",
        profile_revision=1,
        base_uri="https://host.example",
        manifest_path="/manifest",
        invoke_path_template="/invoke",
        reconcile_path_template="/reconcile",
        supported_protocol_versions=("host-capability-protocol/1",),
        workload_identity_ref="workload/worker",
        credential_ref="credentials/host-hmac",
        manifest_binding_policy="declared",
    ).model_copy(update=changes)


def apply(
    store: HostConnectorManagementStore,
    trust: HostManagementTrust,
    approved: HostConnectorProfileVersion,
    revision: int,
    active: bool = True,
    operation: str | None = None,
) -> Any:
    return store.apply(trust, approved, revision, operation or str(uuid4()), active)


def counts(dsn: str, namespace: str) -> tuple[int, ...]:
    with psycopg.connect(dsn) as connection:
        return tuple(
            connection.execute(
                f"SELECT count(*) FROM {table} WHERE deployment_namespace=%s", (namespace,)
            ).fetchone()[0]
            for table in (
                "host_connector_profiles",
                "host_connector_bindings",
                "host_connector_management_receipts",
                "host_connector_management_audit",
            )
        )


def test_empty_read_and_missing_disable(managed: Any, connector_dsn: str) -> None:
    store, _, _, trust = managed
    value = store.read(trust, profile())
    assert (value.binding, value.profile, value.revision) == (None, None, 0)
    with pytest.raises(HostManagementConflict):
        apply(store, trust, profile(), 0, False)
    assert counts(connector_dsn, store.deployment_namespace) == (0, 0, 0, 0)


def test_disable_reenable_preserves_actual_profile_and_original_receipt(
    managed: Any,
    connector_dsn: str,
) -> None:
    store, native, management, trust = managed
    first, desired, operation = profile(), profile(profile_revision=2), str(uuid4())
    created = apply(store, trust, first, 0, operation=operation)
    assert created.profile == first and created.revision == 1
    value = store.read(trust, desired)
    assert value.profile == first and value.approved_profile == desired
    disabled = apply(store, trust, desired, 1, False)
    assert disabled.binding.active is False and disabled.profile == first
    assert native.get_profile("example", "main", 2) is None
    assert native.resolve_binding("example", "tenant-a") is None
    assert store.read(trust, desired).binding == disabled.binding
    replay = apply(store, trust, first, 0, operation=operation)
    assert replay.replayed and replay.binding == created.binding and replay.profile == first
    with pytest.raises(HostManagementConflict):
        apply(store, trust, first, 0, False, operation)
    active = apply(store, trust, desired, 2)
    assert active.binding.active and active.profile == desired and active.revision == 3
    newer = replace(trust, revision=2, fingerprint="b" * 64)
    management.approve(newer, 1)
    with pytest.raises(HostManagementUnavailable):
        apply(store, trust, first, 0, operation=operation)
    with pytest.raises(HostManagementConflict):
        apply(store, newer, first, 0, operation=operation)
    assert store.read(newer, first).profile == desired
    assert counts(connector_dsn, store.deployment_namespace) == (2, 1, 3, 3)


@pytest.mark.parametrize(
    "changes",
    [
        {"base_uri": "https://other.example"},
        {"manifest_binding_policy": "legacy"},
        {"reconcile_path_template": None},
        {"supported_protocol_versions": ("other/1",)},
        {"status": "deprecated"},
    ],
)
def test_native_full_immutability(managed: Any, changes: dict[str, Any]) -> None:
    _, native, _, _ = managed
    original = profile()
    native.publish_profile(original)
    changed = HostConnectorProfileVersion.model_validate({**original.model_dump(), **changes})
    with pytest.raises(ValueError, match="immutable"):
        native.publish_profile(changed)
    assert native.get_profile("example", "main", 1) == original


@pytest.mark.parametrize("drift", ["stored_digest", "model_with_matching_stored_digest"])
def test_publication_checks_stored_digest_and_full_model(
    managed: Any,
    connector_dsn: str,
    drift: str,
) -> None:
    store, native, _, trust = managed
    original = profile()
    native.publish_profile(original)
    with psycopg.connect(connector_dsn) as connection:
        if drift == "stored_digest":
            connection.execute(
                "UPDATE host_connector_profiles SET profile_digest=%s "
                "WHERE deployment_namespace=%s",
                ("f" * 64, store.deployment_namespace),
            )
        else:
            connection.execute(
                "UPDATE host_connector_profiles SET base_uri='https://drift.example' "
                "WHERE deployment_namespace=%s",
                (store.deployment_namespace,),
            )
    with pytest.raises(HostManagementConflict):
        apply(store, trust, original, 0)
    assert counts(connector_dsn, store.deployment_namespace) == (1, 0, 0, 0)


def test_scope_current_approval_and_missing_actual_profile(
    managed: Any, connector_dsn: str
) -> None:
    store, _, _, trust = managed
    for changed in (
        replace(trust, host_app_id="other"),
        replace(trust, namespace_id="other"),
        replace(trust, product_id="other"),
    ):
        with pytest.raises(HostManagementUnavailable):
            store.read(changed, profile(host_app_id=changed.host_app_id))
    with pytest.raises(HostManagementUnavailable):
        apply(store, trust, profile(host_app_id="other"), 0)
    other = HostConnectorManagementStore(connector_dsn, deployment_namespace=f"other-{uuid4()}")
    with pytest.raises(HostManagementUnavailable):
        other.read(trust, profile())
    apply(store, trust, profile(), 0)
    with psycopg.connect(connector_dsn) as connection:
        connection.execute(
            "DELETE FROM host_connector_profiles WHERE deployment_namespace=%s",
            (store.deployment_namespace,),
        )
    with pytest.raises(HostManagementUnavailable, match="profile"):
        store.read(trust, profile())
    with pytest.raises(HostManagementUnavailable, match="profile"):
        apply(store, trust, profile(profile_revision=2), 1, False)
    assert counts(connector_dsn, store.deployment_namespace) == (0, 1, 1, 1)


def freeze(dsn: str, namespace: str, host: str | None = None) -> None:
    store_frozen_manifest(
        dsn,
        deployment_namespace=namespace,
        manifest_digest="d" * 64,
        connector_id="main",
        profile_revision=1,
        manifest_payload={"original": "immutable historical bytes"},
        host_app_id=host,
    )


@pytest.mark.parametrize("owners", [(), ("foreign",), ("example", "foreign"), ("example",)])
def test_legacy_freeze_requires_preexisting_unique_same_host(
    managed: Any,
    connector_dsn: str,
    owners: tuple[str, ...],
) -> None:
    store, native, _, trust = managed
    for owner in owners:
        native.publish_profile(profile(host_app_id=owner))
    freeze(connector_dsn, store.deployment_namespace)
    with psycopg.connect(connector_dsn) as connection:
        before = connection.execute(
            "SELECT row_to_json(f) FROM host_manifest_freezes f WHERE deployment_namespace=%s",
            (store.deployment_namespace,),
        ).fetchall()
    if owners == ("example",):
        assert apply(store, trust, profile(), 0).revision == 1
        assert native.publish_profile(profile()) == profile()
    else:
        with pytest.raises(HostManagementConflict):
            apply(store, trust, profile(), 0)
        with pytest.raises(ValueError, match="ownership"):
            native.publish_profile(profile())
    with psycopg.connect(connector_dsn) as connection:
        assert (
            connection.execute(
                "SELECT row_to_json(f) FROM host_manifest_freezes f WHERE deployment_namespace=%s",
                (store.deployment_namespace,),
            ).fetchall()
            == before
        )
    assert counts(connector_dsn, store.deployment_namespace)[0] == len(owners)


def test_host_scoped_freezes_allow_multiple_hosts_and_disable_preserves_history(
    managed: Any,
    connector_dsn: str,
) -> None:
    store, native, _, trust = managed
    native.publish_profile(profile(host_app_id="foreign"))
    freeze(connector_dsn, store.deployment_namespace, "foreign")
    apply(store, trust, profile(), 0)
    freeze(connector_dsn, store.deployment_namespace, "example")
    with psycopg.connect(connector_dsn) as connection:
        before = [
            connection.execute(
                f"SELECT row_to_json(t) FROM {table} t "
                "WHERE deployment_namespace=%s ORDER BY host_app_id",
                (store.deployment_namespace,),
            ).fetchall()
            for table in ("host_manifest_revisions", "host_connector_profiles")
        ]
    apply(store, trust, profile(profile_revision=2), 1, False)
    with psycopg.connect(connector_dsn) as connection:
        after = [
            connection.execute(
                f"SELECT row_to_json(t) FROM {table} t "
                "WHERE deployment_namespace=%s ORDER BY host_app_id",
                (store.deployment_namespace,),
            ).fetchall()
            for table in ("host_manifest_revisions", "host_connector_profiles")
        ]
    assert before == after


def test_native_all_writers_enforce_actual_cas(managed: Any) -> None:
    store, native, _, trust = managed
    native.publish_profile(profile())
    binding = HostConnectorBinding(
        host_app_id="example",
        namespace_id="tenant-a",
        connector_id="main",
        profile_revision=1,
        binding_revision=1,
    )
    with pytest.raises(ValueError, match="creation"):
        native.bind(binding.model_copy(update={"binding_revision": 2}))
    assert native.bind(binding).binding_revision == 1
    assert native.bind(binding).binding_revision == 2
    with pytest.raises(ValueError, match="CAS"):
        native.bind(binding)
    with pytest.raises(HostManagementConflict):
        apply(store, trust, profile(), 1)
    assert native.bind(binding.model_copy(update={"binding_revision": 2})).binding_revision == 3
    apply(store, trust, profile(), 3, False)
    with pytest.raises(ValueError, match="CAS"):
        native.bind(binding.model_copy(update={"binding_revision": 4}))
    assert apply(store, trust, profile(), 4).revision == 5


@pytest.mark.parametrize("initial", [False, True])
@pytest.mark.parametrize("failure", ["receipt", "audit"])
def test_failure_rolls_back_publication_binding_receipt_audit(
    managed: Any,
    connector_dsn: str,
    monkeypatch: pytest.MonkeyPatch,
    failure: str,
    initial: bool,
) -> None:
    store, _, _, trust = managed
    if not initial:
        apply(store, trust, profile(), 0)
    before = counts(connector_dsn, store.deployment_namespace)
    if failure == "audit":

        def fail(connection: Any, *args: Any) -> None:
            connection.execute("SELECT 1/0")

        monkeypatch.setattr(store, "_audit", fail)
    else:
        with psycopg.connect(connector_dsn) as connection:
            connection.execute(
                sql.SQL(
                    "ALTER TABLE host_connector_management_receipts "
                    "ADD CONSTRAINT forced_failure CHECK (deployment_namespace <> {}) NOT VALID"
                ).format(sql.Literal(store.deployment_namespace)),
            )
    try:
        with pytest.raises((psycopg.errors.DivisionByZero, psycopg.errors.CheckViolation)):
            apply(store, trust, profile(profile_revision=2), 0 if initial else 1)
        assert counts(connector_dsn, store.deployment_namespace) == before
        assert store.read(trust, profile()).profile == (None if initial else profile())
    finally:
        if failure == "receipt":
            with psycopg.connect(connector_dsn) as connection:
                connection.execute(
                    "ALTER TABLE host_connector_management_receipts DROP CONSTRAINT forced_failure"
                )


def test_error_after_real_commit_replays_original_snapshot(
    managed: Any,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    store, _, management, trust = managed
    operation = str(uuid4())
    original = store._management.authorized

    @contextmanager
    def lost_reply(value: Any) -> Iterator[Any]:
        with original(value) as connection:
            yield connection
        raise ConnectionError("reply lost after real commit")

    monkeypatch.setattr(store._management, "authorized", lost_reply)
    with pytest.raises(ConnectionError):
        apply(store, trust, profile(), 0, operation=operation)
    monkeypatch.setattr(store._management, "authorized", original)
    apply(store, trust, profile(profile_revision=2), 1)
    replay = apply(store, trust, profile(), 0, operation=operation)
    assert replay.replayed and replay.revision == 1 and replay.profile == profile()
    assert management.read(trust).revision == 0  # B1 receipts/actions are independent.


def _race(
    dsn: str,
    namespace: str,
    trust: HostManagementTrust,
    start: Any,
    results: Any,
    operation: str,
    mode: str,
    revision: int,
) -> None:
    start.wait()
    try:
        if mode == "native":
            binding = PostgresHostConnectorRegistry(dsn, deployment_namespace=namespace).bind(
                HostConnectorBinding(
                    host_app_id="example",
                    namespace_id="tenant-a",
                    connector_id="main",
                    profile_revision=1,
                    binding_revision=revision,
                )
            )
            result = ("ok", binding.binding_revision, False)
        else:
            value = apply(
                HostConnectorManagementStore(dsn, deployment_namespace=namespace),
                trust,
                profile(),
                revision,
                operation=operation,
            )
            result = ("ok", value.revision, value.replayed)
        results.put(result)
    except (HostManagementConflict, ValueError):
        results.put(("conflict",))


@pytest.mark.parametrize("mode", ["same_operation", "different_operation", "native_api", "native"])
def test_independent_process_cas_and_replay(managed: Any, connector_dsn: str, mode: str) -> None:
    store, native, _, trust = managed
    revision = 0
    if mode in {"native_api", "native"}:
        apply(store, trust, profile(), 0)
        revision = 1
    context = multiprocessing.get_context("spawn")
    start, results, operation = context.Event(), context.Queue(), str(uuid4())
    modes = (
        ("native", "native")
        if mode == "native"
        else (("native", "api") if mode == "native_api" else ("api", "api"))
    )
    children = [
        context.Process(
            target=_race,
            args=(
                connector_dsn,
                store.deployment_namespace,
                trust,
                start,
                results,
                operation if mode == "same_operation" else str(uuid4()),
                writer,
                revision,
            ),
        )
        for writer in modes
    ]
    for child in children:
        child.start()
    start.set()
    outcomes = [results.get(timeout=20) for _ in children]
    for child in children:
        child.join(timeout=20)
        assert child.exitcode == 0
    if mode == "same_operation":
        assert sorted(outcomes) == [("ok", 1, False), ("ok", 1, True)]
    else:
        assert sorted(outcomes) == [("conflict",), ("ok", revision + 1, False)]
    assert native.resolve_binding("example", "tenant-a").binding_revision == revision + 1


@pytest.mark.parametrize("lock", ["binding", "profile", "manifest"])
def test_expiry_after_native_lock_wait_rolls_back(
    managed: Any,
    connector_dsn: str,
    lock: str,
) -> None:
    store, _, management, trust = managed
    apply(store, trust, profile(), 0)
    short = replace(
        trust,
        revision=2,
        fingerprint="b" * 64,
        expires_at=datetime.now(UTC) + timedelta(seconds=0.65),
    )
    management.approve(short, 1)
    with psycopg.connect(connector_dsn) as blocker:
        if lock == "manifest":
            blocker.execute(
                "SELECT pg_advisory_xact_lock(hashtextextended(%s,0))",
                (json.dumps(["host-manifest-revision", store.deployment_namespace, "main", 1]),),
            )
        else:
            table = "host_connector_bindings" if lock == "binding" else "host_connector_profiles"
            blocker.execute(
                f"SELECT * FROM {table} WHERE deployment_namespace=%s FOR UPDATE",
                (store.deployment_namespace,),
            )
        with ThreadPoolExecutor(max_workers=1) as executor:
            pending = executor.submit(apply, store, short, profile(), 1)
            time.sleep(0.75)
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
    assert counts(connector_dsn, store.deployment_namespace) == (1, 1, 1, 1)


def test_manifest_publish_uses_exact_freeze_lock(managed: Any, connector_dsn: str) -> None:
    store, native, _, _ = managed
    with psycopg.connect(connector_dsn) as blocker:
        blocker.execute(
            "SELECT pg_advisory_xact_lock(hashtextextended(%s,0))",
            (json.dumps(["host-manifest-revision", store.deployment_namespace, "main", 1]),),
        )
        with ThreadPoolExecutor(max_workers=1) as executor:
            pending = executor.submit(native.publish_profile, profile())
            time.sleep(0.1)
            assert not pending.done()
            blocker.commit()
            assert pending.result(timeout=3) == profile()


def test_rotation_waits_for_apply_and_fences_replay(managed: Any, connector_dsn: str) -> None:
    store, _, management, trust = managed
    apply(store, trust, profile(), 0)
    newer, operation = replace(trust, revision=2, fingerprint="b" * 64), str(uuid4())
    with psycopg.connect(connector_dsn) as blocker:
        blocker.execute(
            "SELECT * FROM host_connector_bindings WHERE deployment_namespace=%s FOR UPDATE",
            (store.deployment_namespace,),
        )
        with ThreadPoolExecutor(max_workers=2) as executor:
            pending = executor.submit(apply, store, trust, profile(), 1, False, operation)
            until = time.monotonic() + 1
            while True:
                with psycopg.connect(connector_dsn) as observer:
                    waiting = observer.execute(
                        "SELECT count(*) FROM pg_stat_activity WHERE wait_event_type='Lock' "
                        "AND query LIKE 'SELECT * FROM host_connector_bindings%'"
                    ).fetchone()[0]
                if waiting:
                    break
                assert time.monotonic() < until
                time.sleep(0.01)
            approval = executor.submit(management.approve, newer, 1)
            time.sleep(0.05)
            assert not approval.done()
            blocker.commit()
            assert pending.result(timeout=3).revision == 2
            approval.result(timeout=3)
    with pytest.raises(HostManagementUnavailable):
        apply(store, trust, profile(), 1, False, operation)
    assert store.read(newer, profile()).binding.active is False


@pytest.mark.parametrize(
    "revision,operation,active",
    [
        (True, str(uuid4()), True),
        (-1, str(uuid4()), True),
        (2**53 - 1, str(uuid4()), True),
        (0, "invalid", True),
        (0, str(uuid4()).upper(), True),
        (0, str(uuid4()), 1),
    ],
)
def test_apply_input_validation(managed: Any, revision: Any, operation: str, active: Any) -> None:
    store, _, _, trust = managed
    with pytest.raises(ValueError):
        store.apply(trust, profile(), revision, operation, active)


def test_stale_cas_rolls_back_new_profile_publication(managed: Any, connector_dsn: str) -> None:
    store, _, _, trust = managed
    apply(store, trust, profile(), 0)
    with pytest.raises(HostManagementConflict):
        apply(store, trust, profile(profile_revision=2), 0)
    assert counts(connector_dsn, store.deployment_namespace) == (1, 1, 1, 1)


def test_b1_and_b2_operation_ids_are_independent(managed: Any) -> None:
    store, _, management, trust = managed
    operation = str(uuid4())
    record = HostRegistryRecord(
        host_app_id="example",
        namespace_id="tenant-a",
        issuer="https://idp.example",
        audience="runtime",
        jwks_uri="https://idp.example/keys",
        allowed_origins=("https://host.example",),
        algorithms=("RS256",),
        policy_version="1",
    )
    assert management.apply(trust, record, 0, operation).revision == 1
    assert apply(store, trust, profile(), 0, operation=operation).revision == 1
    assert management.apply(trust, record, 0, operation).replayed
    assert apply(store, trust, profile(), 0, operation=operation).replayed
