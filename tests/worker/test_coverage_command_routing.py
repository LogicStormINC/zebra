"""Pure consumer transport and qualification proof; not native execution evidence."""

from datetime import UTC, datetime, timedelta
from functools import partial
from types import SimpleNamespace
from uuid import uuid4

import pytest
from agent_runtime.command_wakeup_consumer import CommandWakeupConsumer, PickupOutcome
from agent_storage.postgres.command_wakeup_handoff import CommandHandoff, HandoffStatus
from agent_storage.postgres.worker_capability import (
    WorkerCapabilityExpiredError,
    WorkerCapabilityLease,
    WorkerCapabilityLostError,
)
from zebra_agent_worker.command_process_state import (
    CommandWorkerCapability,
    strict_worker_configuration_digest,
)
from zebra_agent_worker.coverage_recovery_preparation import NativeCoverageRecoveryCheck

from tests.worker.coverage_model_cloud_fixtures import dsn, model_cloud, postgres_dsn  # noqa: F401
from tests.worker.test_coverage_dispatch import (
    complete_execution_discovery,
    native_worker,  # noqa: F401
)
from tests.worker.test_coverage_worker_readiness import structural  # noqa: F401


def test_native_fixture_deadline_reader_advances_across_64k_chunks():
    from hashlib import sha256
    from time import monotonic

    from agent_core.domain.artifact_objects import ArtifactObjectPutRequest
    from agent_storage import S3ArtifactObjectStore

    from tests.agent_storage.test_s3_artifact_objects import _expectation, _FakeS3Client

    body = bytes(range(256)) * 513
    expectation = _expectation().model_copy(
        update={
            "sha256": sha256(body).hexdigest(),
            "size_bytes": len(body),
        }
    )
    client = _FakeS3Client()
    objects = S3ArtifactObjectStore(
        client,
        bucket="fixture",
        deadline_client_factory=lambda timeout: client,
    )
    receipt = objects.put_if_absent(ArtifactObjectPutRequest(expectation=expectation, payload=body))
    assert (
        objects.read_version_verified_before(
            expectation,
            receipt.object_version,
            monotonic() + 5,
        )
        == body
    )


@pytest.mark.parametrize("busy", ["lock", "database", "none"])
def test_only_completed_execution_discovery_advances_capability_progress(monkeypatch, busy):
    import asyncio

    from agent_runtime.command_wakeup_consumer import _Busy

    consumer = CommandWakeupConsumer(
        "unused",
        deployment_namespace="test",
        owner="test",
        execute_claimed=lambda lease: None,
        quarantine=lambda *args: None,
    )

    async def discover(*args):
        if busy == "database":
            raise _Busy
        return ()

    monkeypatch.setattr(consumer, "_db", discover)

    async def check():
        try:
            if busy == "lock":
                await consumer._polling["execution"].acquire()
            assert await consumer.poll("execution") == ()
            assert consumer._execution_discovery_generation == int(busy == "none")
        finally:
            if busy == "lock":
                consumer._polling["execution"].release()
            await consumer.close()

    asyncio.run(check())


def test_only_exact_native_recovery_checker_matching_actual_service_qualifies(structural):  # noqa: F811
    settings, service, _ = structural
    runtime = service._coverage_runtime
    checker = NativeCoverageRecoveryCheck(runtime, service)
    digest = strict_worker_configuration_digest(
        "unused-dsn",
        "readiness-test",
        settings,
        service.execute_claimed_session,
        checker,
    )
    assert digest is not None
    factory = runtime.objects._deadline_client_factory
    runtime.objects._deadline_client_factory = None
    assert (
        strict_worker_configuration_digest(
            "unused-dsn",
            "readiness-test",
            settings,
            service.execute_claimed_session,
            checker,
        )
        is None
    )
    assert (
        strict_worker_configuration_digest(
            "unused-dsn",
            "readiness-test",
            settings,
            service.execute_claimed_session,
            partial(runtime.recovery_check, service),
        )
        == digest
    )
    runtime.objects._deadline_client_factory = factory
    for wrong in (
        NativeCoverageRecoveryCheck(runtime, object()),
        NativeCoverageRecoveryCheck(object(), service),
        SimpleNamespace(runtime=runtime, service=service),
        partial(lambda *args: {}, service),
    ):
        assert (
            strict_worker_configuration_digest(
                "unused-dsn",
                "readiness-test",
                settings,
                service.execute_claimed_session,
                wrong,
            )
            is None
        )


@pytest.mark.parametrize("error", ["capability", "recovery"])
def test_consumer_transports_registration_token_and_capability_loss_defers(monkeypatch, error):
    from agent_runtime import command_wakeup_consumer

    token = WorkerCapabilityLease(uuid4(), uuid4(), 1, datetime.now(UTC) + timedelta(seconds=30))

    async def quarantine(*args):
        pytest.fail("lawful incompatible command quarantined")

    consumer = CommandWakeupConsumer(
        "unused",
        deployment_namespace="test",
        owner="spoofed-owner-text",
        execute_claimed=lambda lease: pytest.fail("incompatible strict command executed"),
        quarantine=quarantine,
        consumer_capability=lambda: token,
    )
    resolved = SimpleNamespace(scope=object(), accepted_event_id=uuid4())
    calls = []

    def handoff(*args, **kwargs):
        calls.append(kwargs)
        assert kwargs["consumer_capability"] is token
        failure = (
            WorkerCapabilityLostError
            if error == "capability"
            else command_wakeup_consumer.CoverageRecoveryDeferred
        )
        raise failure("deferred")

    monkeypatch.setattr(command_wakeup_consumer, "handoff_command", handoff)
    try:
        assert consumer._admit(resolved, None) is PickupOutcome.DEFERRED
        assert consumer._slots.acquire(blocking=False)
        consumer._slots.release()
        assert len(calls) == 1
    finally:
        import asyncio

        asyncio.run(consumer.close())


def test_ordinary_consumer_does_not_fabricate_process_proof(monkeypatch):
    import asyncio

    from agent_runtime import command_wakeup_consumer

    async def quarantine(*args):
        pytest.fail("ordinary command quarantined")

    consumer = CommandWakeupConsumer(
        "unused",
        deployment_namespace="test",
        owner="ordinary",
        execute_claimed=lambda lease: None,
        quarantine=quarantine,
    )
    resolved = SimpleNamespace(scope=object(), accepted_event_id=uuid4())

    def handoff(*args, **kwargs):
        assert kwargs["consumer_capability"] is None
        return CommandHandoff(HandoffStatus.DUPLICATE, uuid4(), resolved.accepted_event_id)

    monkeypatch.setattr(command_wakeup_consumer, "handoff_command", handoff)
    try:
        assert consumer._admit(resolved, None) is PickupOutcome.ACKNOWLEDGED
    finally:
        asyncio.run(consumer.close())


def test_process_token_is_scoped_to_qualified_actual_consumer(structural, monkeypatch):  # noqa: F811
    from time import monotonic

    settings, service, checker = structural
    capability = CommandWorkerCapability(
        "unused-dsn", "readiness-test", settings, service.execute_claimed_session, checker
    )
    consumer = object.__new__(CommandWakeupConsumer)
    consumer._dsn, consumer._namespace = "unused-dsn", "readiness-test"
    consumer._coverage_check, consumer._closed = checker, False
    lease = WorkerCapabilityLease(uuid4(), uuid4(), 1, datetime.now(UTC) + timedelta(seconds=30))
    monkeypatch.setattr(capability._store, "register", lambda *args, **kwargs: lease)
    monkeypatch.setattr(capability._store, "revoke", lambda *args: None)
    assert capability.lease_for(consumer) is None
    capability.consumer_tick(consumer, 1, monotonic())
    assert capability.lease_for(consumer) is None
    complete_execution_discovery(consumer)
    capability.consumer_tick(consumer, 1, monotonic())
    assert capability.lease_for(consumer) is lease
    assert capability.lease_for(SimpleNamespace(_closed=False)) is None
    consumer._closed = True
    assert capability.lease_for(consumer) is None
    capability.close()
    assert capability.lease_for(consumer) is None


@pytest.mark.parametrize("failure", ["expired", "revoked", "epoch", "config", "race-revoked"])
def test_only_natural_expiry_can_register_new_process_after_fresh_work(
    structural,  # noqa: F811
    monkeypatch,
    failure,  # noqa: F811
):
    from time import monotonic

    settings, service, checker = structural
    capability = CommandWorkerCapability(
        "unused-dsn",
        "readiness-test",
        settings,
        service.execute_claimed_session,
        checker,
    )
    consumer = object.__new__(CommandWakeupConsumer)
    consumer._dsn, consumer._namespace = "unused-dsn", "readiness-test"
    consumer._coverage_check, consumer._closed = checker, False
    first = WorkerCapabilityLease(uuid4(), uuid4(), 1, datetime.now(UTC) + timedelta(seconds=30))
    registered = []
    revoked = []

    def register(process, **kwargs):
        registered.append((process, kwargs))
        if "expired_lease" in kwargs:
            assert kwargs["expired_lease"] is first
            assert process != first.process_id
            if failure == "race-revoked":
                raise WorkerCapabilityLostError("revoked after expired heartbeat")
            return WorkerCapabilityLease(
                process, first.epoch, 1, datetime.now(UTC) + timedelta(seconds=30)
            )
        return first

    def heartbeat(*args, **kwargs):
        if failure in {"expired", "race-revoked"}:
            raise WorkerCapabilityExpiredError("naturally expired")
        raise WorkerCapabilityLostError(failure)

    monkeypatch.setattr(capability._store, "register", register)
    monkeypatch.setattr(capability._store, "heartbeat", heartbeat)
    monkeypatch.setattr(capability._store, "revoke", lambda lease: revoked.append(lease))
    complete_execution_discovery(consumer)
    capability.consumer_tick(consumer, 1, monotonic())
    capability.consumer_tick(consumer, 1, monotonic())  # no fresh work, no repair
    assert len(registered) == 1
    capability.consumer_tick(consumer, 2, monotonic())  # recovery alone is not progress
    assert len(registered) == 1
    complete_execution_discovery(consumer)
    if failure == "expired":
        capability.consumer_tick(consumer, 2, monotonic())
        assert (
            len(registered) == 2 and capability.lease_for(consumer).process_id != first.process_id
        )
    else:
        with pytest.raises(WorkerCapabilityLostError):
            capability.consumer_tick(consumer, 2, monotonic())
        assert capability.lease_for(consumer) is None and revoked == [first]
        capability.consumer_tick(consumer, 3, monotonic())
        assert len(registered) == (2 if failure == "race-revoked" else 1)


@pytest.mark.parametrize("native_worker", ["empty"], indirect=True)
@pytest.mark.parametrize("proof", ["absent", "observational", "matching"])
def test_native_broker_consumers_require_actual_registration_not_matching_owner(
    native_worker,  # noqa: F811
    proof,  # noqa: F811
):
    import asyncio

    from agent_core.domain.events import EventType
    from agent_storage.postgres.command_wakeup_relay import _validated_body
    from agent_storage.postgres.worker_capability import PostgresWorkerCapabilities

    from tests.worker.coverage_model_cloud_fixtures import NAMESPACE
    from tests.worker.test_coverage_dispatch import _start_native_capability

    env = native_worker
    _start_native_capability(env)
    with env.database.connect() as connection:
        outbox = connection.execute(
            "SELECT * FROM broker_outbox WHERE operation_id=%s",
            (env.native_event.payload["command_id"],),
        ).fetchone()
        body = _validated_body(connection, NAMESPACE, outbox)

    class Delivery:
        def __init__(self):
            self.body, self.acks, self.requeues = body, 0, 0

        async def ack(self):
            self.acks += 1

        async def requeue(self):
            self.requeues += 1

    delivery = Delivery()
    if proof == "matching":
        consumer = env.native_consumer
    else:
        observed = PostgresWorkerCapabilities(env.dsn, deployment_namespace=NAMESPACE).current(
            configuration_digest=env.native_digest,
        )[0]
        assert observed.attestation is None

        async def quarantine(*args):
            pytest.fail("unqualified consumer quarantined lawful strict command")

        consumer = CommandWakeupConsumer(
            env.dsn,
            deployment_namespace=NAMESPACE,
            owner="native-strict-worker",
            execute_claimed=lambda lease: pytest.fail(
                "unqualified consumer executed strict command"
            ),
            quarantine=quarantine,
            coverage_check=env.native_checker,
            consumer_capability=None if proof == "absent" else lambda: observed,
        )

    async def consume():
        try:
            return await consumer.on_delivery(delivery)
        finally:
            await consumer.close()

    outcome = asyncio.run(consume())
    events = env.events.list_for_session(env.session)
    with env.database.connect() as connection:
        receipts = connection.execute(
            "SELECT count(*) AS n FROM command_handoff_receipts"
        ).fetchone()["n"]
    if proof == "matching":
        assert outcome is PickupOutcome.SCHEDULED and delivery.acks == 1 and delivery.requeues == 0
        assert receipts == 1 and any(
            e.event_type is EventType.COVERAGE_REPORT_CERTIFIED for e in events
        )
        assert not any(r.url.path == "/chat/completions" for r in env.native_requests)
    else:
        assert outcome is PickupOutcome.DEFERRED and delivery.acks == 0 and delivery.requeues == 1
        assert receipts == 0 and not any(
            e.event_type is EventType.COVERAGE_REPORT_CERTIFIED for e in events
        )
