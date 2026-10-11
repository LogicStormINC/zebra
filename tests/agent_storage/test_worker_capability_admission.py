"""Pure caller-transaction/process gates; native rollback/concurrency is separate."""

import os
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from agent_storage.postgres.command_coverage_admission_migration import (
    COMMAND_COVERAGE_ADMISSION_MIGRATION,
)
from agent_storage.postgres.migrations import MIGRATIONS
from agent_storage.postgres.worker_capability import (
    STRICT_WORKER_CONTRACT,
    WorkerCapabilityExpiredError,
    WorkerCapabilityLease,
    WorkerCapabilityLostError,
    check_worker_capability_clock,
    pin_worker_capability,
)
from agent_storage.worker_capability_configuration import worker_capability_configuration_digest
from zebra_agent_config import load_settings

from tests.agent_storage.test_postgres_command_wakeup import dsn, postgres_dsn  # noqa: F401


class Rows:
    def __init__(self, value):
        self.value = value

    def fetchone(self):
        return self.value

    def fetchall(self):
        return self.value


class Connection:
    def __init__(self):
        self.now = datetime.now(UTC)
        self.epoch = uuid4()
        self.process = uuid4()
        self.expires = self.now + timedelta(seconds=30)
        self.available = True
        self.calls = []

    def execute(self, sql, params=()):
        self.calls.append((sql, params))
        if "zebra_schema_migrations" in sql:
            return Rows(
                [{"version": m.version, "name": m.name, "checksum": m.checksum} for m in MIGRATIONS]
            )
        if "SELECT epoch FROM control_plane_epochs" in sql:
            return Rows({"epoch": self.epoch})
        if "FROM worker_process_capabilities" in sql:
            return Rows(
                {
                    "process_id": self.process,
                    "epoch": self.epoch,
                    "sequence": 1,
                    "expires_at": self.expires,
                }
                if self.available
                else None
            )
        if "clock_timestamp() AS now" in sql:
            return Rows({"now": self.now})
        return Rows(None)


def test_contract_catalog_and_final_trigger_are_versioned_and_not_uuid_pinned():
    assert STRICT_WORKER_CONTRACT == (
        "cov-exec-01:model:bounded-multipart:same-session:validation-mode:v3"
    )
    from agent_storage.postgres.worker_continuation_migration import WORKER_CONTINUATION_MIGRATION

    assert MIGRATIONS[-2:] == (
        COMMAND_COVERAGE_ADMISSION_MIGRATION, WORKER_CONTINUATION_MIGRATION,
    )
    assert len({m.version for m in MIGRATIONS}) == len(MIGRATIONS)
    sql = " ".join(COMMAND_COVERAGE_ADMISSION_MIGRATION.statements)
    requirement = sql.split("CREATE TABLE command_coverage_requirements", 1)[1].split(
        "CREATE INDEX", 1
    )[0]
    assert "process_id" not in requirement
    assert "DEFERRABLE INITIALLY DEFERRED" in sql
    assert "clock_timestamp()" in sql and "broker_outbox" in sql
    assert "host_expiry<=final_now" in sql and "context_expiry<=final_now" in sql
    assert "runtime_deadline<=final_now" in sql
    assert "e.created_at + make_interval" in sql and "max_runtime_seconds" in sql


@pytest.mark.parametrize("proof", [None, True, "owner-name", "a" * 64])
def test_unknown_consumer_refuses_before_schema_or_ownership_access(proof):
    connection = Connection()
    with pytest.raises(WorkerCapabilityLostError):
        pin_worker_capability(
            connection,
            "test",
            contract=STRICT_WORKER_CONTRACT,
            configuration_digest="a" * 64,
            consumer_capability=proof,
            require_process=True,
        )
    assert connection.calls == []


def test_observational_lease_and_foreign_process_cannot_attest():
    connection = Connection()
    observational = WorkerCapabilityLease(
        connection.process, connection.epoch, 1, connection.expires
    )
    for proof in (
        observational,
        replace(observational, attestation="b" * 64, local_pid=os.getpid() + 1),
    ):
        with pytest.raises(WorkerCapabilityLostError):
            pin_worker_capability(
                connection,
                "test",
                contract=STRICT_WORKER_CONTRACT,
                configuration_digest="a" * 64,
                consumer_capability=proof,
                require_process=True,
            )
    assert connection.calls == []


def test_caller_connection_pins_epoch_then_process_and_hashes_token():
    from hashlib import sha256

    connection = Connection()
    proof = WorkerCapabilityLease(
        connection.process,
        connection.epoch,
        1,
        connection.expires,
        attestation="b" * 64,
        local_pid=os.getpid(),
    )
    pinned = pin_worker_capability(
        connection,
        "test",
        contract=STRICT_WORKER_CONTRACT,
        configuration_digest="a" * 64,
        consumer_capability=proof,
        require_process=True,
    )
    assert pinned.process_id == proof.process_id
    sqls = [sql for sql, _ in connection.calls]
    epoch = next(i for i, sql in enumerate(sqls) if "FROM control_plane_epochs" in sql)
    process = next(i for i, sql in enumerate(sqls) if "FROM worker_process_capabilities" in sql)
    assert epoch < process
    assert "FOR SHARE" in sqls[epoch] and "FOR SHARE" in sqls[process]
    assert connection.calls[process][1][-1] == sha256(proof.attestation.encode()).hexdigest()
    assert proof.attestation not in repr(proof)
    connection.now = connection.expires
    with pytest.raises(WorkerCapabilityLostError):
        check_worker_capability_clock(connection, pinned)


def test_live_compatible_replacement_is_selected_by_config_not_previous_process():
    connection = Connection()
    first = pin_worker_capability(
        connection, "test", contract=STRICT_WORKER_CONTRACT, configuration_digest="a" * 64
    )
    connection.process = uuid4()
    second = pin_worker_capability(
        connection, "test", contract=STRICT_WORKER_CONTRACT, configuration_digest="a" * 64
    )
    assert first.process_id != second.process_id
    connection.available = False
    with pytest.raises(WorkerCapabilityLostError):
        pin_worker_capability(
            connection, "test", contract=STRICT_WORKER_CONTRACT, configuration_digest="a" * 64
        )


def test_descriptor_binds_operator_settings_and_objects_but_omits_transport_credentials():
    settings = replace(load_settings(env={}), profile="cloud")
    commands = replace(
        settings.command_delivery,
        relay_url="amqp://user:first@broker/vhost",
        consumer_url="amqp://user:first@broker/vhost",
    )
    settings = replace(settings, command_delivery=commands)

    def digest(config=settings, **changes):
        return worker_capability_configuration_digest(
            config,
            **(
                {
                    "namespace": "test",
                    "bucket": "actual",
                    "key_prefix": "prefix",
                    "object_endpoint": "https://fixture-s3.example",
                }
                | changes
            ),
        )

    original = digest()
    rotated = replace(
        settings,
        command_delivery=replace(
            commands,
            relay_url="amqp://user:rotated@broker/vhost",
            consumer_url="amqp://user:rotated@broker/vhost",
        ),
    )
    assert digest(rotated) == original
    assert digest(bucket="other") != original and digest(namespace="other") != original
    assert digest(key_prefix="other") != original
    assert digest(object_endpoint="https://different-s3.example") != original
    assert digest(object_endpoint="https://user:secret@fixture-s3.example?token=secret") == original
    assert digest(replace(settings, command_delivery=replace(commands, batch_size=2))) != original
    with pytest.raises(ValueError):
        digest(bucket="")


@pytest.mark.parametrize("loss", ["natural", "revoked", "epoch", "config", "sequence", "schema"])
def test_native_only_natural_expiry_allows_new_registration(dsn, loss):  # noqa: F811
    from agent_storage import bootstrap_control_plane_epoch, rotate_control_plane_epoch
    from agent_storage.postgres.database import PostgresDatabase
    from agent_storage.postgres.worker_capability import PostgresWorkerCapabilities

    namespace = "native-expiry-test"
    bootstrap_control_plane_epoch(dsn, deployment_namespace=namespace)
    store = PostgresWorkerCapabilities(dsn, deployment_namespace=namespace)
    first = store.register(uuid4(), configuration_digest="a" * 64, ttl_seconds=1)
    database = PostgresDatabase(dsn, deployment_namespace=namespace)
    with database.connect() as connection:
        connection.execute("SELECT pg_sleep(1.05)")
        if loss == "revoked":
            connection.execute(
                "UPDATE worker_process_capabilities SET revoked_at=clock_timestamp()"
            )
        elif loss == "config":
            connection.execute(
                "UPDATE worker_process_capabilities SET configuration_digest=%s", ("b" * 64,)
            )
        elif loss == "sequence":
            connection.execute("UPDATE worker_process_capabilities SET sequence=sequence+1")
        elif loss == "schema":
            connection.execute("UPDATE worker_process_capabilities SET schema_oid=0")
    if loss == "epoch":
        rotate_control_plane_epoch(dsn, deployment_namespace=namespace)
    if loss == "natural":
        with pytest.raises(WorkerCapabilityExpiredError):
            store.heartbeat(first, configuration_digest="a" * 64)
        second = store.register(uuid4(), configuration_digest="a" * 64, expired_lease=first)
        assert second.process_id != first.process_id and second.attestation != first.attestation
        assert store.current(configuration_digest="a" * 64) == (second,)
        with database.connect() as connection:
            assert connection.execute(
                "SELECT revoked_at FROM worker_process_capabilities WHERE process_id=%s",
                (first.process_id,),
            ).fetchone()["revoked_at"]
    else:
        with pytest.raises(WorkerCapabilityLostError) as error:
            store.heartbeat(first, configuration_digest="a" * 64)
        assert type(error.value) is WorkerCapabilityLostError
        with pytest.raises(WorkerCapabilityLostError):
            store.register(uuid4(), configuration_digest="a" * 64, expired_lease=first)
        with database.connect() as connection:
            assert (
                connection.execute(
                    "SELECT count(*) AS n FROM worker_process_capabilities"
                ).fetchone()["n"]
                == 1
            )


@pytest.mark.parametrize("race", ["revoke", "epoch"])
def test_native_expired_replacement_rechecks_operator_change(dsn, race):  # noqa: F811
    from agent_storage import bootstrap_control_plane_epoch, rotate_control_plane_epoch
    from agent_storage.postgres.database import PostgresDatabase
    from agent_storage.postgres.worker_capability import PostgresWorkerCapabilities

    namespace = "native-expiry-race"
    bootstrap_control_plane_epoch(dsn, deployment_namespace=namespace)
    store = PostgresWorkerCapabilities(dsn, deployment_namespace=namespace)
    first = store.register(uuid4(), configuration_digest="a" * 64, ttl_seconds=1)
    with PostgresDatabase(dsn, deployment_namespace=namespace).connect() as connection:
        connection.execute("SELECT pg_sleep(1.05)")
    with pytest.raises(WorkerCapabilityExpiredError):
        store.heartbeat(first, configuration_digest="a" * 64)
    if race == "revoke":
        store.revoke(first)
    else:
        rotate_control_plane_epoch(dsn, deployment_namespace=namespace)
    with pytest.raises(WorkerCapabilityLostError):
        store.register(uuid4(), configuration_digest="a" * 64, expired_lease=first)


@pytest.mark.parametrize("change", ["later", "duplicate", "malformed"])
def test_strict_marker_cannot_hide_behind_absent_root_or_malformed_binding(change):
    from agent_storage.postgres.command_coverage_admission import _identity

    root, later = uuid4(), uuid4()
    row = {
        "root_session_id": root,
        "prepared_session_id": root,
        "prepared_sequence": 2,
        "payload": {"coverage_admission": None},
        "snapshot_json": None,
    }
    if change == "later":
        row["prepared_session_id"] = later

    class RawSource:
        def execute(self, sql, params):
            assert "marker.payload ? 'coverage_admission'" in sql and "LIMIT 65" in sql
            return Rows([row, row] if change == "duplicate" else [row])

    with pytest.raises(WorkerCapabilityLostError):
        _identity(RawSource(), "test", root)


def test_strict_identity_refuses_at_task_runtime_deadline(monkeypatch):
    from types import SimpleNamespace

    from agent_storage.postgres import command_coverage_admission as module

    now = datetime.now(UTC)
    root, task = uuid4(), uuid4()
    context = SimpleNamespace(
        namespace_id="ns", host_app_id="host", expires_at=now + timedelta(minutes=1)
    )
    host = SimpleNamespace(
        host_context=context,
        grant_digest="digest",
        namespace_id="ns",
        host_app_id="host",
        authority_issuer="issuer",
        grant_expires_at=now + timedelta(minutes=1),
    )
    binding = SimpleNamespace(
        host_capability=host,
        task_id=str(task),
        binding_digest="digest",
        binding_revision=1,
    )
    monkeypatch.setattr(module.TaskBindingSnapshot, "model_validate", lambda value: binding)
    monkeypatch.setattr(module, "host_context_digest", lambda value: "digest")
    monkeypatch.setattr(
        module,
        "validate_coverage_admission",
        lambda *args, **kwargs: SimpleNamespace(max_runtime_seconds=1),
    )
    monkeypatch.setattr(
        module,
        "strict_command_source",
        lambda *args: {
            "root_session_id": root,
            "task_id": task,
            "snapshot_json": {},
            "binding_digest": "digest",
            "binding_revision": 1,
            "payload": {"host_context": {}, "coverage_admission": {}},
            "prepared_created_at": now - timedelta(seconds=1),
        },
    )

    class Clock:
        def execute(self, sql, params=()):
            return Rows({"now": now} if "clock_timestamp" in sql else {"issuer": "issuer"})

    calls = []
    original_source = module.strict_command_source

    def source(*args):
        calls.append("source")
        return original_source(*args)

    class LockedClock(Clock):
        def execute(self, sql, params=()):
            if "pg_advisory_xact_lock_shared" in sql:
                assert "hashtextextended(%s, 0)" in sql and params == (f"test:{task}",)
                calls.append("lock")
            return super().execute(sql, params)

    monkeypatch.setattr(module, "strict_command_source", source)
    with pytest.raises(WorkerCapabilityLostError, match="runtime deadline"):
        module._identity(LockedClock(), "test", root, lock_task_authority=True)
    assert calls == ["source", "lock", "source"]


@pytest.mark.parametrize("after_wait", ["expired", "renewed", "unchanged"])
def test_consumer_pin_rechecks_authority_after_capability_wait(monkeypatch, after_wait):
    from agent_storage.postgres import command_coverage_admission as module

    session, event = uuid4(), uuid4()
    identity = {"task_id": uuid4(), "binding_revision": 1}
    calls = []
    deadline = datetime.now(UTC) + timedelta(seconds=5)

    def current(*args, **kwargs):
        calls.append(("identity", kwargs["lock_task_authority"]))
        if kwargs.get("authority_deadlines") is not None:
            kwargs["authority_deadlines"].append(deadline)
        if len(calls) > 1:
            if after_wait == "expired":
                raise WorkerCapabilityLostError("Host or runtime expired during capability wait")
            if after_wait == "renewed":
                return identity | {"binding_revision": 2}
        return identity

    lease = WorkerCapabilityLease(uuid4(), uuid4(), 1, datetime.now(UTC) + timedelta(seconds=30))

    def pin(*args, **kwargs):
        calls.append(("capability", None))
        return lease

    class Canonical:
        def execute(self, sql, params):
            if "session_events" in sql:
                return Rows({"session_id": session, "payload": {"kind": "run"}})
            return Rows(
                identity | {"contract": STRICT_WORKER_CONTRACT, "configuration_digest": "a" * 64,
                            "continuation_protocol": None, "recovery_reason": None}
            )

    monkeypatch.setattr(module, "_identity", current)
    monkeypatch.setattr(module, "pin_worker_capability", pin)
    monkeypatch.setattr(
        module, "check_worker_capability_clock", lambda *args: calls.append(("clock", None))
    )
    if after_wait == "unchanged":
        pinned = module.pin_command_consumer(
            Canonical(), "test", event, lease, lock_task_authority=True
        )
        assert pinned.process_id == lease.process_id and pinned.attestation == lease.attestation
        assert pinned.expires_at == deadline and lease.expires_at > deadline
    else:
        with pytest.raises(WorkerCapabilityLostError):
            module.pin_command_consumer(Canonical(), "test", event, lease, lock_task_authority=True)
    assert calls[:3] == [("identity", True), ("capability", None), ("identity", True)]
