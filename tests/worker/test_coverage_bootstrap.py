"""Bootstrap composition checks and first-bind tests in disposable PG schemas."""

from dataclasses import replace
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from unittest.mock import MagicMock
from uuid import uuid4

import psycopg
import pytest
from agent_core.application.coverage_semantic import semantic_check
from agent_core.application.session_bootstrap import (
    SessionBootstrapCommand,
    SessionBootstrapService,
)
from agent_core.application.workspace_projection import rebuild_workspace
from agent_core.contracts.session_commands import SessionCommand, SessionCommandKind
from agent_core.domain.cloud_artifact_payloads import CloudArtifactPayloadLifecycleStatus
from agent_core.domain.cloud_artifact_requests import ArtifactMetadataQuery
from agent_core.domain.coverage_contracts import CoverageRefusalReason, CoverageRefusedError
from agent_core.domain.coverage_execution import CoverageExecutionBudget
from agent_core.domain.coverage_task_admission import CoverageTaskAdmission
from agent_core.domain.coverage_validation import manifest_digest
from agent_core.domain.events import EventActor, EventType, SessionEvent
from agent_core.domain.identifiers import SessionId, TaskId
from agent_core.domain.leases import LeaseFence
from agent_core.domain.task_bindings import TaskBindingSnapshot, host_context_digest
from agent_core.ports.aggregate_mutation import WorkerMutationAuthority
from agent_core.ports.task_admission_transaction import TaskAdmissionRequest
from agent_storage import (
    PostgresCloudArtifactPayloadStore,
    PostgresEventStore,
    PostgresLeaseStore,
    S3ArtifactObjectStore,
    bootstrap_control_plane_epoch,
)
from agent_storage.postgres.task_admission import PostgresTaskAdmissionTransaction
from zebra_agent_worker import coverage_bootstrap as module

from tests.agent_integrations.test_coverage_snapshot import AUTHORITY, CONTRACT
from tests.agent_integrations.test_coverage_snapshot_preparation import setup_source
from tests.agent_storage.test_command_wakeup import _binding
from tests.agent_storage.test_postgres_command_wakeup import (  # noqa: F401
    NAMESPACE,
    dsn,
    postgres_dsn,
)
from tests.agent_storage.test_s3_artifact_objects import _FakeS3Client


def inputs(*, strict=True, v2=False):
    now = datetime.now(UTC)
    from tests.agent_integrations.test_coverage_snapshot_v2 import (
        V2_AUTHORITY,
        V2_CONTRACT,
        V2_SOURCE,
    )

    host = (V2_AUTHORITY if v2 else AUTHORITY).model_copy(
        update={"expires_at": now + timedelta(hours=1)},
    )
    contract = (V2_CONTRACT if v2 else CONTRACT).model_copy(
        update={"checks": (semantic_check("review").contract_check,)},
    )
    admission = CoverageTaskAdmission(
        contract=contract,
        **({"source_ref": V2_SOURCE} if v2 else {"history_ref": "history"}),
        model_profile="review",
        execution_budget=CoverageExecutionBudget(max_attempts=100, max_input_bytes=1000),
        max_model_calls=100,
        max_model_tokens=100,
        max_runtime_seconds=60,
    )
    bootstrap = SessionBootstrapService().build(
        SessionBootstrapCommand(
            title="bootstrap fixture",
            user_input="synthetic coverage",
            workspace_root="/tmp/coverage",
            host_context=host,
            coverage_admission=admission if strict else None,
        )
    )
    session = bootstrap.session.session_id
    if v2:
        from tests.worker.test_coverage_v2_fixtures import setup_neutral_source

        source, wire = setup_neutral_source(
            session_id=session, authority=host, contract=contract, now=lambda: datetime.now(UTC),
        )
    else:
        source, wire, _ = setup_source(
            session_id=session, authority=host, now=lambda: datetime.now(UTC),
        )

    def mutate(name, value):
        if name in {"get", "create"}:
            value["snapshot"].update(
                contract_digest=contract.digest,
                manifest_digest=manifest_digest(contract, wire.records),
            )
        return value

    wire.mutate = mutate
    data = _binding(
        str(session), tenant=host.namespace_id, workspace=host.workspace_ref
    ).model_dump()
    data["host_capability"].update(
        host_context=host,
        host_app_id=host.host_app_id,
        authority_issuer=host.origin,
        connector_id=host.host_app_id,
        grant_digest=host_context_digest(host),
        grant_expires_at=host.expires_at,
        manifest_digest=source.host.manifest.digest,
    )
    binding = TaskBindingSnapshot.model_validate(data)
    return SimpleNamespace(
        bootstrap=bootstrap,
        host=host,
        admission=admission,
        session=session,
        source=source,
        wire=wire,
        task_binding=binding,
    )


@pytest.fixture
def component(monkeypatch):
    env = inputs()
    env.events = list(env.bootstrap.events)
    env.fence = LeaseFence(control_plane_epoch=uuid4(), fencing_token=1, owner_instance_id="test")
    env.order = []
    env.locked = False
    metadata = PostgresCloudArtifactPayloadStore("dbname=unit", deployment_namespace=NAMESPACE)
    env.kwargs = dict(
        dsn="dbname=unit",
        deployment_namespace=NAMESPACE,
        metadata=metadata,
        objects=MagicMock(),
        source=env.source,
        host_authority=env.host,
        admission=env.admission,
        task_id=TaskId(env.session),
        session_id=env.session,
        run_id="run-1",
        fence=env.fence,
        authority=lambda: WorkerMutationAuthority(
            deployment_namespace=NAMESPACE,
            session_id=env.session,
            expected_stream_revision=env.events[-1].sequence,
            lease_fence=env.fence,
        ),
        check_authority=lambda: env.order.append("check"),
        sync_events=lambda: env.order.append("sync"),
    )
    connection = MagicMock()

    def execute(query, params=()):
        result = MagicMock()
        result.fetchone.return_value = None
        if "SELECT task.active_segment_id" in query:
            result.fetchone.return_value = {
                "active_segment_id": env.session,
                "snapshot_json": env.task_binding.model_dump(mode="json"),
                "binding_digest": env.task_binding.binding_digest,
                "namespace_id": env.host.namespace_id,
                "current_version": getattr(env, "stream_revision", env.events[-1].sequence),
            }
        elif "SELECT binding_digest FROM task_binding_snapshots" in query:
            result.fetchone.return_value = {"binding_digest": env.task_binding.binding_digest}
        if "event_type='coverage_manifest_committed'" in query:
            result.fetchall.return_value = []
        return result

    connection.execute.side_effect = execute
    context = MagicMock()

    def enter():
        env.locked = True
        return connection

    def leave(*args):
        env.locked = False

    context.__enter__.side_effect = enter
    context.__exit__.side_effect = leave
    monkeypatch.setattr(module.PostgresDatabase, "connect", lambda self: context)

    def history(self, sid):
        assert not env.locked, "Event-store connection must not be opened inside held locks"
        return env.events

    monkeypatch.setattr(module.PostgresEventStore, "list_for_session", history)
    for name in ("lock_session_lease_boundary", "assert_current_lease_fence", "_lock_task"):
        monkeypatch.setattr(module, name, lambda *a: None)
    monkeypatch.setattr(module, "lock_run", lambda *a: (None, 2))
    env.publisher = MagicMock()
    monkeypatch.setattr(module, "PostgresCoverageArtifactPublisher", env.publisher)
    env.store = MagicMock()
    env.store.bind.side_effect = lambda *a, **kw: env.order.append("bind") or 4
    monkeypatch.setattr(module, "PostgresCoverageStore", lambda *a, **kw: env.store)
    return env


def test_component_order_and_full_binding(component, monkeypatch):
    env = component

    def publish(self, identifier, kind, body, maximum, validate, expires):
        validate()
        self.store.check_authority()
        env.order.append("publish")
        assert self.store.binding.verify_manifest(body) == env.wire.records
        assert kind == "coverage_manifest" and maximum == 33554432
        return f"artifact://{identifier}"

    def read(self, identifier, descriptor, maximum, now):
        env.order.append("readback")
        return f"artifact://{identifier}", env.wire.records

    monkeypatch.setattr(module.CoverageArtifacts, "publish", publish)
    monkeypatch.setattr(module.CoverageArtifacts, "manifest", read)
    result = module.bootstrap_cloud_coverage(**env.kwargs)
    assert result.records == env.wire.records and result.sequence == 4
    assert result.store is env.store
    assert env.order.index("publish") < env.order.index("readback") < env.order.index("bind")
    assert env.order[env.order.index("bind") + 1] == "sync"
    assert env.publisher.call_args.kwargs["metadata"] is env.kwargs["metadata"]


@pytest.mark.parametrize(
    "problem",
    ["legacy", "admission", "host", "history", "session", "fence", "deployment", "metadata"],
)
def test_identity_refused_before_host(component, problem):
    env = component
    if problem == "legacy":
        env.events[2] = env.events[2].model_copy(
            update={
                "payload": {
                    k: v for k, v in env.events[2].payload.items() if k != "coverage_admission"
                },
            }
        )
    elif problem == "admission":
        env.kwargs["admission"] = env.admission.model_copy(update={"max_model_calls": 99})
    elif problem == "host":
        env.kwargs["host_authority"] = env.host.model_copy(update={"host_app_id": "other"})
    elif problem == "history":
        env.kwargs["admission"] = env.admission.model_copy(update={"history_ref": "other"})
    elif problem == "session":
        env.kwargs["session_id"] = SessionId(uuid4())
    elif problem == "fence":
        env.kwargs["fence"] = env.fence.model_copy(update={"fencing_token": 2})
    elif problem == "deployment":
        env.kwargs["deployment_namespace"] = "other"
    elif problem == "metadata":
        env.kwargs["metadata"] = PostgresCloudArtifactPayloadStore(
            "dbname=other", deployment_namespace=NAMESPACE
        )
    with pytest.raises(ValueError):
        module.bootstrap_cloud_coverage(**env.kwargs)
    assert not env.wire.calls
    env.publisher.assert_not_called()
    env.store.bind.assert_not_called()


@pytest.mark.parametrize(
    "problem", ["bytes", "rows", "id", "contract", "readback", "revoked", "uncertain"]
)
def test_source_and_readback_refusal_never_bind(component, monkeypatch, problem):
    env = component
    get = env.source.get
    env.kwargs["snapshot_id"] = "snapshot"

    def corrupt(snapshot_id, *, authority):
        prepared = get(snapshot_id, authority=authority)
        if problem == "bytes":
            return replace(prepared, manifest_bytes=b"corrupt")
        if problem == "rows":
            return replace(prepared, records=())
        if problem == "id":
            return replace(prepared, manifest_artifact_id=uuid4())
        if problem == "contract":
            return replace(
                prepared,
                descriptor=prepared.descriptor.model_copy(update={"contract_digest": "a" * 64}),
            )
        return prepared

    monkeypatch.setattr(env.source, "get", corrupt)
    if problem == "readback":
        monkeypatch.setattr(module.CoverageArtifacts, "publish", lambda *a: "artifact://wrong")
        monkeypatch.setattr(module.CoverageArtifacts, "manifest", lambda *a: None)
    elif problem == "revoked":
        env.wire.revoked = True
    elif problem == "uncertain":
        # No descriptor is provided by an uncertain Effect; never invent a new key.
        env.kwargs.pop("snapshot_id")
        env.wire.mutate = lambda name, value: {"status": "uncertain"}
    with pytest.raises(ValueError):
        module.bootstrap_cloud_coverage(**env.kwargs)
    env.store.bind.assert_not_called()
    if problem != "readback":
        env.publisher.assert_not_called()


@pytest.fixture
def cloud(dsn, request):  # noqa: F811 - schema fixture, never the pre-bound publication fixture
    mode = getattr(request, "param", True)
    env = inputs(strict=mode is not False, v2=mode == "v2")
    PostgresTaskAdmissionTransaction(dsn, deployment_namespace=NAMESPACE).admit(
        TaskAdmissionRequest(
            events=tuple(env.bootstrap.events),
            session=env.bootstrap.session,
            workspace=rebuild_workspace(list(env.bootstrap.events)),
            binding=env.task_binding,
        )
    )
    bootstrap_control_plane_epoch(dsn, deployment_namespace=NAMESPACE)
    env.leases = PostgresLeaseStore(dsn, deployment_namespace=NAMESPACE)
    env.fence = env.leases.acquire(
        env.session, owner_instance_id="bootstrap-test", ttl=timedelta(minutes=5)
    ).fence
    env.events = PostgresEventStore(dsn, deployment_namespace=NAMESPACE)
    env.metadata = PostgresCloudArtifactPayloadStore(dsn, deployment_namespace=NAMESPACE)
    env.client = _FakeS3Client()
    env.objects = S3ArtifactObjectStore(env.client, bucket="bootstrap-tests")
    env.dsn = dsn
    env.revision = env.events.list_for_session(env.session)[-1].sequence

    def sync():
        env.revision = env.events.list_for_session(env.session)[-1].sequence

    env.kwargs = dict(
        dsn=dsn,
        deployment_namespace=NAMESPACE,
        metadata=env.metadata,
        objects=env.objects,
        source=env.source,
        host_authority=env.host,
        admission=env.admission,
        task_id=TaskId(env.session),
        session_id=env.session,
        run_id="run-1",
        fence=env.fence,
        authority=lambda: WorkerMutationAuthority(
            deployment_namespace=NAMESPACE,
            session_id=env.session,
            expected_stream_revision=env.revision,
            lease_fence=env.fence,
        ),
        check_authority=lambda: None,
        sync_events=sync,
    )
    return env


def counts(env):
    with psycopg.connect(env.dsn) as connection:
        return tuple(
            connection.execute(
                f"SELECT count(*) FROM {table} WHERE deployment_namespace=%s",
                (NAMESPACE,),
            ).fetchone()[0]
            for table in ("coverage_runs", "artifact_payload_metadata", "session_events")
        )


def test_real_first_bind_readback_and_fresh_instance_retry(cloud):
    env = cloud
    before = counts(env)
    assert before[:2] == (0, 0)
    result = module.bootstrap_cloud_coverage(**env.kwargs)
    assert (
        result.binding.verify_manifest(
            result.artifacts.read_payload_bytes(
                env.source.manifest_artifact_id(result.binding.snapshot),
            )
        )
        == result.records
    )
    assert result.store.counts("ns", "run-1") == (2, 0)
    events = env.events.list_for_session(env.session)
    assert [e.event_type for e in events[-2:]] == [
        EventType.COVERAGE_ARTIFACT_MATERIALIZED,
        EventType.COVERAGE_MANIFEST_COMMITTED,
    ]
    assert events[-1].sequence == result.sequence
    after = counts(env)
    assert after == (1, 1, before[2] + 2)
    env.kwargs["source"], _, _ = setup_source(
        session_id=env.session,
        authority=env.host,
        now=lambda: datetime.now(UTC),
    )
    # Retain the adapted semantic Host transport for this fresh source instance.
    env.kwargs["source"].host.invoke = env.source.host.invoke
    retry = module.bootstrap_cloud_coverage(**env.kwargs, snapshot_id="snapshot")
    assert retry.binding == result.binding and retry.sequence == result.sequence
    assert counts(env) == after and len(env.client.objects) == 1
    key = env.wire.calls[0]["idempotencyKey"]
    again = module.bootstrap_cloud_coverage(**{**env.kwargs, "source": env.source})
    assert again.binding == result.binding and counts(env) == after
    assert (
        next(
            c["idempotencyKey"]
            for c in reversed(env.wire.calls)
            if c["toolName"].endswith("create")
        )
        == key
    )


@pytest.mark.parametrize("stage", ["upload", "receipt", "bind"])
@pytest.mark.parametrize("cloud", [True, "v2"], indirect=True)
def test_real_crash_recovery_without_duplicate_events(cloud, monkeypatch, stage):
    env = cloud
    before = counts(env)
    target, method = (
        (env.objects, "put_if_absent")
        if stage == "upload"
        else (module.PostgresCoverageArtifactPublisher, "_record_receipts")
        if stage == "receipt"
        else (module.PostgresCoverageStore, "bind")
    )
    original = getattr(target, method)

    def crash(*args, **kwargs):
        original(*args, **kwargs)
        raise RuntimeError("lost acknowledgement")

    with monkeypatch.context() as patch:
        patch.setattr(target, method, crash)
        with pytest.raises(RuntimeError, match="lost acknowledgement"):
            module.bootstrap_cloud_coverage(**env.kwargs)
    prepared = env.source.get("snapshot", authority=env.host)
    record = env.metadata.get_metadata(
        ArtifactMetadataQuery(
            deployment_namespace=NAMESPACE,
            session_id=env.session,
            artifact_id=prepared.manifest_artifact_id,
        )
    )
    if stage != "bind":
        assert record.lifecycle_status == CloudArtifactPayloadLifecycleStatus.STAGED
        assert counts(env) == (0, 1, before[2])
        # Actual cloud facade refuses staged evidence, even though S3 has bytes.
        binding = module.CoverageRunBinding(
            namespace="ns",
            session_id=env.session,
            task_id=TaskId(env.session),
            run_id="run-1",
            contract=env.admission.contract,
            snapshot=module.CoverageSnapshot(
                **prepared.descriptor.model_dump(), manifest_artifact_ref=record.uri
            ),
            manifest_artifact_digest=record.reservation.sha256,
        )
        facade = module.CloudCoverageArtifacts(
            binding=binding,
            deployment_namespace=NAMESPACE,
            metadata=env.metadata,
            objects=env.objects,
            publisher=module.PostgresCoverageArtifactPublisher(
                env.dsn, deployment_namespace=NAMESPACE, metadata=env.metadata, objects=env.objects
            ),
            authority=env.kwargs["authority"],
            check_authority=lambda: None,
            sync_events=env.kwargs["sync_events"],
        )
        assert facade.get_payload(prepared.manifest_artifact_id) is None
        with pytest.raises(ValueError):
            facade.read_payload_bytes(prepared.manifest_artifact_id)
    recovered = module.bootstrap_cloud_coverage(**env.kwargs, snapshot_id="snapshot")
    assert recovered.store.counts("ns", "run-1") == (2, 0)
    assert counts(env) == (1, 1, before[2] + 2)
    assert len(env.client.objects) == 1


@pytest.mark.parametrize("problem", ["stop", "cancel", "fence", "revocation", "contract", "host"])
def test_real_recovery_refusals_preserve_old_run(cloud, problem):
    env = cloud
    result = module.bootstrap_cloud_coverage(**env.kwargs)
    if problem == "stop":
        previous = env.events.list_for_session(env.session)[-1]
        command = SessionCommand(
            session_id=env.session,
            kind=SessionCommandKind.STOP,
            expected_revision=previous.sequence,
            idempotency_key="bootstrap-stop",
        )
        env.events.append(
            SessionEvent.create(
                session_id=env.session,
                sequence=previous.sequence + 1,
                event_type=EventType.SESSION_COMMAND_ACCEPTED,
                actor=EventActor.USER,
                payload=command.event_payload(),
                idempotency_key=command.idempotency_key,
            )
        )
    elif problem == "cancel":
        result.store.cancel("ns", "run-1", fence=env.fence)
    elif problem == "fence":
        env.leases.release(env.session, fence=env.fence)
        env.leases.acquire(env.session, owner_instance_id="replacement", ttl=timedelta(minutes=5))
    elif problem == "revocation":

        def refused():
            raise CoverageRefusedError(CoverageRefusalReason.AUTHORITY_INVALID)

        env.kwargs["check_authority"] = refused
    elif problem == "contract":
        env.kwargs["admission"] = env.admission.model_copy(update={"max_model_calls": 99})
    elif problem == "host":
        env.kwargs["host_authority"] = env.host.model_copy(update={"grant_id": "other"})
    before = counts(env)
    calls = len(env.wire.calls)
    with pytest.raises((ValueError, RuntimeError)):
        module.bootstrap_cloud_coverage(**env.kwargs, snapshot_id="snapshot")
    assert counts(env) == before and len(env.wire.calls) == calls
    assert result.store.counts("ns", "run-1") == (2, 0)


@pytest.mark.parametrize("cloud", [False], indirect=True)
def test_real_ordinary_task_cannot_bootstrap(cloud):
    before = counts(cloud)
    with pytest.raises(ValueError, match="persisted Task identity"):
        module.bootstrap_cloud_coverage(**cloud.kwargs)
    assert not cloud.wire.calls and counts(cloud) == before


@pytest.mark.parametrize("problem", ["authority", "fence", "snapshot"])
def test_change_after_source_preparation_never_publishes(component, monkeypatch, problem):
    env = component
    original = env.source.create
    revoked = [False]

    def change(*args, **kwargs):
        prepared = original(*args, **kwargs)
        if problem == "authority":
            revoked[0] = True
        elif problem == "fence":
            env.fence = env.fence.model_copy(update={"fencing_token": 2})
        else:
            env.source.host.now = lambda: prepared.descriptor.expires_at
        return prepared

    # Use a stable supplier whose returned authority can change during preparation.
    supplier = env.kwargs["authority"]

    def current():
        if revoked[0]:
            raise CoverageRefusedError(CoverageRefusalReason.AUTHORITY_INVALID)
        return supplier()

    env.kwargs["authority"] = current
    monkeypatch.setattr(env.source, "create", change)
    with pytest.raises(ValueError):
        module.bootstrap_cloud_coverage(**env.kwargs)
    env.publisher.assert_not_called()
    env.store.bind.assert_not_called()


def test_persisted_authority_change_during_publication_never_binds(component, monkeypatch):
    env = component

    def publish(self, *args):
        env.task_binding = env.task_binding.model_copy(update={"zebra_policy_digest": "f" * 64})
        self.store.check_authority()
        pytest.fail("changed Task authority was accepted")

    monkeypatch.setattr(module.CoverageArtifacts, "publish", publish)
    with pytest.raises(ValueError, match="authority changed during publication"):
        module.bootstrap_cloud_coverage(**env.kwargs)
    env.store.bind.assert_not_called()


@pytest.mark.parametrize("target", ["authority", "nested_fence", "supplied_fence"])
@pytest.mark.parametrize("storage", ["copy", "extras"])
def test_unknown_typed_authority_fields_refused_before_io(component, target, storage):
    env = component
    raw = env.kwargs["authority"]()
    value = raw if target == "authority" else raw.lease_fence
    if storage == "copy":
        value = value.model_copy(update={"unknown": True})
    else:
        value = value.model_copy()
        object.__setattr__(value, "__pydantic_extra__", {"unknown": True})
    if target == "authority":
        raw = value
    elif target == "nested_fence":
        raw = raw.model_copy(update={"lease_fence": value})
    else:
        env.kwargs["fence"] = value
    env.kwargs["authority"] = lambda: raw
    env.events = []  # Recovery would fail differently if reached.
    with pytest.raises(ValueError, match="unknown attributes"):
        module.bootstrap_cloud_coverage(**env.kwargs)
    assert not env.wire.calls
    env.publisher.assert_not_called()
    env.store.bind.assert_not_called()


def test_copied_nested_authority_fields_are_revalidated(component):
    env = component
    raw = env.kwargs["authority"]()
    raw = raw.model_copy(
        update={
            "lease_fence": raw.lease_fence.model_copy(update={"fencing_token": "invalid"}),
        }
    )
    env.kwargs["authority"] = lambda: raw
    with pytest.raises(ValueError):
        module.bootstrap_cloud_coverage(**env.kwargs)
    assert not env.wire.calls
    env.publisher.assert_not_called()


def test_history_must_match_locked_stream_even_with_current_authority(component):
    env = component
    raw = env.kwargs["authority"]()
    env.stream_revision = raw.expected_stream_revision + 1
    env.kwargs["authority"] = lambda: raw.model_copy(
        update={
            "expected_stream_revision": env.stream_revision,
        }
    )
    with pytest.raises(ValueError, match="mutation revision conflicts"):
        module.bootstrap_cloud_coverage(**env.kwargs)
    assert not env.wire.calls
    env.publisher.assert_not_called()
    env.store.bind.assert_not_called()


def test_real_event_append_between_history_read_and_lock_is_refused(cloud, monkeypatch):
    env = cloud
    before = counts(env)
    original = module.PostgresEventStore.list_for_session
    appended = False

    def read(self, sid):
        nonlocal appended
        history = original(self, sid)
        if not appended:
            appended = True
            self.append(
                SessionEvent.create(
                    session_id=sid,
                    sequence=history[-1].sequence + 1,
                    event_type=EventType.USER_MESSAGE_RECEIVED,
                    actor=EventActor.USER,
                    payload={"content": "synthetic concurrent append"},
                )
            )
        return history

    raw = env.kwargs["authority"]()
    env.kwargs["authority"] = lambda: raw.model_copy(
        update={
            "expected_stream_revision": raw.expected_stream_revision + 1,
        }
    )
    env.kwargs["sync_events"] = lambda: None
    monkeypatch.setattr(module.PostgresEventStore, "list_for_session", read)
    with pytest.raises(ValueError, match="mutation revision conflicts"):
        module.bootstrap_cloud_coverage(**env.kwargs)
    assert appended and not env.wire.calls
    # Only the independently appended Event exists; bootstrap made no writes.
    assert counts(env) == (0, 0, before[2] + 1)
