"""Structural/pure negatives are not a native pickup or a provider-health proof."""

from dataclasses import replace
from functools import partial
from time import monotonic
from types import SimpleNamespace

import pytest
from agent_storage import (
    PostgresCloudArtifactPayloadStore,
    PostgresEventStore,
    PostgresGovernedMemoryStore,
    PostgresLeaseStore,
    PostgresProjectionStore,
    S3ArtifactObjectStore,
)
from zebra_agent_config import load_settings
from zebra_agent_worker.command_process_state import (
    strict_continuation_configuration_digest,
    strict_worker_configuration_digest,
)
from zebra_agent_worker.coverage_composition import CloudCoverageRuntime
from zebra_agent_worker.execution import SessionExecutionService


@pytest.fixture
def structural(monkeypatch):
    """Uninitialized object graph ONLY to exercise pure structural validation."""
    settings = load_settings(env={})
    settings = replace(
        settings,
        profile="cloud",
        model=replace(
            settings.model,
            provider="deepseek",
            base_url="https://api.deepseek.com",
            model="deepseek-v4-pro",
            reviewer_profile="deepseek-v4-pro-reviewer-v1",
            api_key_env="READINESS_TEST_KEY",
        ),
    )
    monkeypatch.setenv("READINESS_TEST_KEY", "test-only")
    service = object.__new__(SessionExecutionService)
    service._settings = settings
    service._deployment_namespace = "readiness-test"
    args = {"deployment_namespace": "readiness-test"}
    service._event_store = PostgresEventStore("unused-dsn", **args)
    service._projection_store = PostgresProjectionStore("unused-dsn", **args)
    service._cloud_memory_store = PostgresGovernedMemoryStore(
        "unused-dsn", cursor_signing_key=b"structural-test-only-signing-key!", **args
    )
    service._task_binding_loader = lambda session: None
    service._cloud_artifact_factory = lambda session: None
    service._claim_service = SimpleNamespace(_lease_store=PostgresLeaseStore("unused-dsn", **args))
    runtime = CloudCoverageRuntime(
        "unused-dsn",
        "readiness-test",
        PostgresCloudArtifactPayloadStore("unused-dsn", **args),
        S3ArtifactObjectStore(
            SimpleNamespace(meta=SimpleNamespace(endpoint_url="https://fixture-s3.example")),
            bucket="test-bucket",
            deadline_client_factory=lambda timeout: None,
        ),
    )
    service._coverage_runtime = runtime
    return settings, service, partial(runtime.recovery_check, service)


def digest(structural):
    settings, service, check = structural
    return strict_worker_configuration_digest(
        "unused-dsn", "readiness-test", settings, service.execute_claimed_session, check
    )


def test_revision_consumer_cannot_match_fingerprint_only_fleet_qualification():
    from uuid import uuid4

    from agent_core.domain.coverage_contracts import coverage_digest
    from agent_storage.postgres.worker_capability import PostgresWorkerCapabilities
    from agent_storage.worker_capability_configuration import (
        CONTINUATION_PROTOCOL,
        NATIVE_CONTINUATION_VERIFIER,
        continuation_configuration_digest,
    )

    configuration = "a" * 64
    old = coverage_digest({
        "configuration": configuration, "consumer": CONTINUATION_PROTOCOL,
        "producer": NATIVE_CONTINUATION_VERIFIER,
    })
    current = continuation_configuration_digest(configuration)
    assert current != old
    assert current == continuation_configuration_digest(configuration)
    store = PostgresWorkerCapabilities("dbname=unused", deployment_namespace="readiness-test")
    revision_only = coverage_digest({
        "configuration": configuration, "consumer": CONTINUATION_PROTOCOL,
        "producer": NATIVE_CONTINUATION_VERIFIER,
        "model_proof": "database-maintained-model-revision/87",
    })
    budget_only = coverage_digest({
        "configuration": configuration, "consumer": CONTINUATION_PROTOCOL,
        "producer": NATIVE_CONTINUATION_VERIFIER,
        "model_proof": "database-maintained-model-revision/87",
        "model_budget": "database-maintained-model-summary/88",
    })
    authority_only = {
        "configuration": configuration, "consumer": CONTINUATION_PROTOCOL,
        "producer": NATIVE_CONTINUATION_VERIFIER,
        "model_proof": "database-maintained-model-revision/87",
        "model_budget": "database-maintained-model-summary/88",
        "task_admission": "database-maintained-task-summary/89",
        "execution_authority": "database-maintained-lineage-versions/90",
    }
    volume_only = {**authority_only, "model_volume": "database-maintained-model-volume/91"}
    indexed_only = {
        **volume_only, "acceptance": "bounded-exact-unit-batches/1",
        "locked_proof_authority": "pure-operation-entry-exit/1",
        "delta_lookups": "tenant-run-key-indexes/92",
    }
    unit_only = {**indexed_only, "membership": "event-sealed-exact-unit-set/93"}
    record_only = {**indexed_only, "membership": "event-sealed-exact-unit-and-record-set/93"}
    for incompatible in (
        old, revision_only, budget_only, coverage_digest(authority_only),
        coverage_digest(volume_only), coverage_digest(indexed_only), coverage_digest(unit_only),
        coverage_digest(record_only),
    ):
        assert current != incompatible
        with pytest.raises(ValueError, match="continuation qualification"):
            store.register(
                uuid4(), configuration_digest=configuration, continuation_digest=incompatible,
            )


def test_continuation_requires_native_preparer_without_changing_legacy_readiness(structural):
    from zebra_agent_worker.coverage_recovery_preparation import NativeCoverageRecoveryCheck

    settings, service, legacy = structural
    args = ("unused-dsn", "readiness-test", settings, service.execute_claimed_session)
    assert strict_worker_configuration_digest(*args, legacy) is not None
    assert strict_continuation_configuration_digest(*args, legacy) is None
    native = NativeCoverageRecoveryCheck(service._coverage_runtime, service)
    assert len(strict_continuation_configuration_digest(*args, native)) == 64
    object.__setattr__(native, "prepare_continuation", lambda *args: None)
    assert strict_continuation_configuration_digest(*args, native) is None


def test_continuation_refuses_substituted_actual_deriver(structural, monkeypatch):
    from zebra_agent_worker import coverage_dispatch
    from zebra_agent_worker.coverage_recovery_preparation import NativeCoverageRecoveryCheck

    settings, service, _ = structural
    monkeypatch.setattr(coverage_dispatch, "derive_semantic_observation", lambda *args: None)
    assert strict_continuation_configuration_digest(
        "unused-dsn", "readiness-test", settings, service.execute_claimed_session,
        NativeCoverageRecoveryCheck(service._coverage_runtime, service),
    ) is None


def test_real_bound_contract_required_not_ready_flag_or_callable(structural):
    settings, service, check = structural
    assert len(digest(structural)) == 64
    assert (
        strict_worker_configuration_digest(
            "unused-dsn", "readiness-test", settings, lambda *args: None, check
        )
        is None
    )
    for substitute in (None, True, lambda *args: {}, partial(lambda *args: {}, service)):
        assert (
            strict_worker_configuration_digest(
                "unused-dsn",
                "readiness-test",
                settings,
                service.execute_claimed_session,
                substitute,
            )
            is None
        )


@pytest.mark.parametrize("change", ["runtime", "namespace", "dsn", "event_dsn", "lease_dsn"])
def test_missing_or_mixed_actual_composition_cannot_publish(structural, change):
    settings, service, check = structural
    if change == "runtime":
        service._coverage_runtime = None
    elif change == "event_dsn":
        service._event_store = PostgresEventStore("other", deployment_namespace="readiness-test")
    elif change == "lease_dsn":
        service._claim_service._lease_store = PostgresLeaseStore(
            "other", deployment_namespace="readiness-test"
        )
    assert (
        strict_worker_configuration_digest(
            "other" if change == "dsn" else "unused-dsn",
            "other" if change == "namespace" else "readiness-test",
            settings,
            service.execute_claimed_session,
            check,
        )
        is None
    )


@pytest.mark.parametrize(
    "dependency", ["_task_binding_loader", "_cloud_artifact_factory", "_cloud_memory_store"]
)
@pytest.mark.parametrize("substitute", [None, True, False])
def test_required_dispatch_wiring_cannot_be_missing_or_boolean(structural, dependency, substitute):
    setattr(structural[1], dependency, substitute)
    assert digest(structural) is None


@pytest.mark.parametrize(
    "dependency", ["_task_binding_loader", "_cloud_artifact_factory", "_cloud_memory_store"]
)
def test_required_dispatch_wiring_attribute_must_exist(structural, dependency):
    delattr(structural[1], dependency)
    assert digest(structural) is None


def test_governed_memory_must_use_same_native_database_and_namespace(structural):
    service = structural[1]
    service._cloud_memory_store = PostgresGovernedMemoryStore(
        "other",
        deployment_namespace="readiness-test",
        cursor_signing_key=b"structural-test-only-signing-key!",
    )
    assert digest(structural) is None
    service._cloud_memory_store = PostgresGovernedMemoryStore(
        "unused-dsn",
        deployment_namespace="other",
        cursor_signing_key=b"structural-test-only-signing-key!",
    )
    assert digest(structural) is None


def test_key_absence_and_configuration_change_not_health(structural, monkeypatch):
    settings, service, check = structural
    original = digest(structural)
    changed = replace(settings, command_delivery=replace(settings.command_delivery, batch_size=2))
    service._settings = changed
    assert digest((changed, service, check)) != original
    monkeypatch.delenv("READINESS_TEST_KEY")
    assert digest((changed, service, check)) is None


def test_secret_transport_userinfo_not_in_configuration_digest(structural):
    settings, service, check = structural
    commands = replace(
        settings.command_delivery,
        publish_enabled=True,
        consume_enabled=True,
        relay_url="amqp://user:first@host:5672/vhost",
        consumer_url="amqp://user:first@host:5672/vhost",
    )
    first = replace(settings, command_delivery=commands)
    service._settings = first
    original = digest((first, service, check))
    second = replace(
        first,
        command_delivery=replace(
            commands,
            relay_url="amqp://user:second@host:5672/vhost",
            consumer_url="amqp://user:second@host:5672/vhost",
        ),
    )
    service._settings = second
    assert digest((second, service, check)) == original
    broker_only = replace(
        second, command_delivery=replace(second.command_delivery, scan_fallback_enabled=False)
    )
    service._settings = broker_only
    assert digest((broker_only, service, check)) is None


def test_non_native_consumer_and_pre_recovery_tick_never_register(structural, monkeypatch):
    from zebra_agent_worker.command_process_state import CommandWorkerCapability

    settings, service, check = structural
    capability = CommandWorkerCapability(
        "unused-dsn", "readiness-test", settings, service.execute_claimed_session, check
    )

    def forbidden(*args, **kwargs):
        raise AssertionError("structural validation must not manufacture native readiness")

    monkeypatch.setattr(capability._store, "register", forbidden)
    capability.consumer_tick(SimpleNamespace(ready=True), 0, monotonic())
    capability.consumer_tick(SimpleNamespace(ready=True), 1, monotonic())
    capability.close()
    capability.consumer_tick(SimpleNamespace(ready=True), 2, monotonic())


def test_structural_tick_generation_and_shutdown_serialize_inflight_publication(
    structural,
    monkeypatch,
):
    """In-memory ordering test only; native publication is checked separately below."""
    from concurrent.futures import ThreadPoolExecutor
    from datetime import UTC, datetime, timedelta
    from threading import Event
    from uuid import uuid4

    from agent_runtime.command_wakeup_consumer import CommandWakeupConsumer
    from agent_storage.postgres.worker_capability import WorkerCapabilityLease
    from zebra_agent_worker.command_process_state import CommandWorkerCapability

    settings, service, check = structural
    capability = CommandWorkerCapability(
        "unused-dsn", "readiness-test", settings, service.execute_claimed_session, check
    )
    consumer = object.__new__(CommandWakeupConsumer)
    consumer._dsn, consumer._namespace = "unused-dsn", "readiness-test"
    consumer._coverage_check, consumer._closed = check, False
    entered, release = Event(), Event()
    calls = []

    def register(process, **kwargs):
        entered.set()
        assert release.wait(2)
        calls.append("register")
        return WorkerCapabilityLease(process, uuid4(), 1, datetime.now(UTC) + timedelta(seconds=30))

    monkeypatch.setattr(capability._store, "register", register)
    monkeypatch.setattr(capability._store, "revoke", lambda lease: calls.append("revoke"))
    from tests.worker.test_coverage_dispatch import complete_execution_discovery

    complete_execution_discovery(consumer)
    with ThreadPoolExecutor(2) as pool:
        ticking = pool.submit(capability.consumer_tick, consumer, 1, monotonic())
        assert entered.wait(2)
        closing = pool.submit(capability.close)
        release.set()
        ticking.result(timeout=2)
        closing.result(timeout=2)
    assert calls == ["register", "revoke"]
    capability.consumer_tick(consumer, 2, monotonic())
    assert calls == ["register", "revoke"]


def test_structural_stalled_recovery_generation_does_not_heartbeat(structural, monkeypatch):
    """No DB-backed ready row: only test whether calls are attempted per new work."""
    from datetime import UTC, datetime, timedelta
    from uuid import uuid4

    from agent_runtime.command_wakeup_consumer import CommandWakeupConsumer
    from agent_storage.postgres.worker_capability import WorkerCapabilityLease
    from zebra_agent_worker.command_process_state import CommandWorkerCapability

    settings, service, check = structural
    capability = CommandWorkerCapability(
        "unused-dsn", "readiness-test", settings, service.execute_claimed_session, check
    )
    consumer = object.__new__(CommandWakeupConsumer)
    consumer._dsn, consumer._namespace = "unused-dsn", "readiness-test"
    consumer._coverage_check, consumer._closed = check, False
    lease = WorkerCapabilityLease(uuid4(), uuid4(), 1, datetime.now(UTC) + timedelta(seconds=30))
    calls = []
    monkeypatch.setattr(capability._store, "register", lambda *a, **k: calls.append(1) or lease)
    monkeypatch.setattr(capability._store, "heartbeat", lambda *a, **k: calls.append(2) or lease)
    from tests.worker.test_coverage_dispatch import complete_execution_discovery

    complete_execution_discovery(consumer)
    capability.consumer_tick(consumer, 1, monotonic() - 6)
    assert calls == []
    capability.consumer_tick(consumer, 0, monotonic())
    capability.consumer_tick(consumer, 1, monotonic())
    for _ in range(10):
        capability.consumer_tick(consumer, 1, monotonic())
    assert calls == [1]
    complete_execution_discovery(consumer)
    capability.consumer_tick(consumer, 2, monotonic())
    assert calls == [1, 2]


# Reuse the fixture-owned schema and real Worker wiring. S3/provider/Host are
# explicit transport fixtures; no registry ready row or consumer callback is injected.
from tests.worker.test_coverage_dispatch import (  # noqa: E402,F401
    dsn,
    model_cloud,
    native_worker,
    postgres_dsn,
)


@pytest.mark.parametrize("native_worker", ["empty"], indirect=True)
@pytest.mark.parametrize(
    "missing", [None, "_task_binding_loader", "_cloud_artifact_factory", "_cloud_memory_store"]
)
def test_native_consumer_pickup_publishes_then_revokes(
    native_worker,  # noqa: F811
    monkeypatch,
    missing,  # noqa: F811
):
    from agent_core.domain.events import EventType
    from agent_storage.postgres.worker_capability import PostgresWorkerCapabilities
    from zebra_agent_worker import command_process, command_process_state
    from zebra_agent_worker.worker_loop_service import WorkerLoopService

    from tests.worker.coverage_model_cloud_fixtures import NAMESPACE

    env = native_worker
    loop_service = WorkerLoopService(env.stores.sessions, env.service)
    check = partial(env.service._coverage_runtime.recovery_check, env.service)
    if missing is not None:
        setattr(env.service, missing, None)
    observed = []
    checked = []
    register = PostgresWorkerCapabilities.register
    heartbeat = PostgresWorkerCapabilities.heartbeat

    def observe_configuration(*args, **kwargs):
        value = strict_worker_configuration_digest(*args, **kwargs)
        checked.append(value)
        return value

    monkeypatch.setattr(
        command_process_state, "strict_worker_configuration_digest", observe_configuration
    )

    def observe_register(store, *args, **kwargs):
        lease = register(store, *args, **kwargs)
        assert lease in store.current(configuration_digest=kwargs["configuration_digest"])
        observed.append(lease)
        return lease

    def observe_heartbeat(store, *args, **kwargs):
        lease = heartbeat(store, *args, **kwargs)
        observed.append(lease)
        return lease

    monkeypatch.setattr(PostgresWorkerCapabilities, "register", observe_register)
    monkeypatch.setattr(PostgresWorkerCapabilities, "heartbeat", observe_heartbeat)
    # Sandbox cleanup is unrelated to this strict empty run / process capability.
    monkeypatch.setattr(command_process, "pin_cloud_engine", lambda settings: object())
    monkeypatch.setattr(command_process, "cleanup_runtime_batch", lambda *args, **kwargs: None)
    result = command_process.CommandWorkerProcess(
        dsn=env.dsn,
        namespace=NAMESPACE,
        settings=env.service._settings,
        execute=env.service.execute_claimed_session,
        maintenance=loop_service.maintenance_once,
        drain=loop_service.drain,
        coverage_check=check,
    ).run(worker_id="native-capability-process", max_cycles=8, idle_sleep_seconds=0.1)
    digest_value = strict_worker_configuration_digest(
        env.dsn, NAMESPACE, env.service._settings, env.service.execute_claimed_session, check
    )
    if missing is not None:
        assert checked and all(value is None for value in checked)
        assert digest_value is None and observed == []
        with env.database.connect() as connection:
            assert (
                connection.execute(
                    "SELECT count(*) AS count FROM worker_process_capabilities"
                ).fetchone()["count"]
                == 0
            )
        return
    assert observed and observed[-1].sequence > observed[0].sequence
    assert observed[0].process_id == observed[-1].process_id
    assert str(env.session) in result.executed_session_ids
    events = env.events.list_for_session(env.session)
    assert any(e.event_type is EventType.COVERAGE_REPORT_CERTIFIED for e in events)
    assert (
        PostgresWorkerCapabilities(env.dsn, deployment_namespace=NAMESPACE).current(
            configuration_digest=digest_value
        )
        == ()
    )
