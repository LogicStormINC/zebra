"""Real owned PostgreSQL, machine HTTP and actual Worker compatibility guard."""

import hashlib
import json
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from datetime import UTC, datetime
from types import SimpleNamespace
from uuid import uuid4

import psycopg
import pytest
from agent_core.domain.agent_definitions import AgentDefinition, AgentRelease, AgentReleaseStatus
from agent_core.domain.identifiers import AgentReleaseId
from agent_core.domain.runtime_assembly import RuntimeAssembly
from agent_core.domain.runtime_bundle import ResolvedRuntimeBundle, seal_runtime_bundle
from agent_core.domain.runtime_gates import CONTRACT_DIGEST
from agent_storage import bootstrap_control_plane_epoch
from agent_storage.postgres.agent_registry import PostgresAgentRegistry
from agent_storage.postgres.host_management import HostManagementStore
from agent_storage.postgres.runtime_gates import RuntimeGateStore
from fastapi import FastAPI
from fastapi.testclient import TestClient
from zebra_agent_api.runtime_gates import PATH, register_runtime_gates
from zebra_agent_api.runtime_gates_config import load_runtime_gate_approval
from zebra_agent_worker.runtime_gates import RuntimeGateWorker

from tests.agent_core.test_bundle_definition import bundle_version
from tests.agent_storage.test_host_management import host_management_dsn  # noqa:F401
from tests.test_bundle_assembly import approved_assembly, settings


def record_response(response, schema):
    import os
    from pathlib import Path

    path = os.environ.get("CA_RUNTIME_GATE_EVIDENCE")
    if path is None:
        return
    target = Path(path)
    assert target.is_absolute()
    values = json.loads(target.read_text()) if target.exists() else []
    values.append({"schema": schema, "body": response.json()})
    target.write_text(json.dumps(values, indent=2) + "\n")
    target.chmod(0o600)


TOKEN = "rtgate_" + "a" * 43


@pytest.fixture
def gate(tmp_path, host_management_dsn, monkeypatch):  # noqa:F811
    cfg = replace(settings(), database_url=host_management_dsn, profile="cloud")
    assembly, catalog = approved_assembly(cfg)
    manifest = assembly.bundle.manifest.model_dump(mode="json")
    manifest["scope"]["namespace_id"] = "gate-" + uuid4().hex[:12]
    scope = manifest["scope"]
    assembly = RuntimeAssembly(
        bundle=seal_runtime_bundle(ResolvedRuntimeBundle.model_validate(manifest)),
        provider_profile=assembly.provider_profile,
    )
    catalog["scope"] = scope
    catalog_path = tmp_path / "catalog.json"
    catalog_path.write_text(json.dumps(catalog))
    catalog_path.chmod(0o600)
    path = tmp_path / "gate.json"
    value = {
        "schema_version": "cloud-agent.runtime-gate-approval/1",
        "scope": scope,
        "namespace_exclusive": True,
        "contract_digest": CONTRACT_DIGEST,
        "audience": "management",
        "actor": "overdoze",
        "trust_revision": 1,
        "credential_sha256": hashlib.sha256(TOKEN.encode()).hexdigest(),
        "expires_at": "2099-01-01T00:00:00Z",
        "actions": ["read", "assess", "drain", "open"],
    }
    path.write_text(json.dumps(value))
    path.chmod(0o600)
    cfg = replace(cfg, runtime_bundle_config=str(catalog_path), runtime_gate_config=str(path))
    approval = load_runtime_gate_approval(str(path), scope["namespace_id"])
    bootstrap_control_plane_epoch(
        host_management_dsn, deployment_namespace=approval.scope.namespace_id
    )
    HostManagementStore(
        host_management_dsn, deployment_namespace=approval.scope.namespace_id
    ).approve(approval.trust, 0)
    store = RuntimeGateStore(host_management_dsn, approval.scope, approval.trust)
    store.initialize()
    version = bundle_version(
        runtime_assembly=assembly,
        authority_issuer=approval.scope.authority_issuer,
        namespace_id=approval.scope.namespace_id,
    )
    registry = PostgresAgentRegistry(
        host_management_dsn, deployment_namespace=approval.scope.namespace_id
    )
    registry.save_definition(
        AgentDefinition(
            definition_id=version.definition_id,
            authority_issuer=version.authority_issuer,
            namespace_id=version.namespace_id,
            name="native",
            description="gate fixture",
            revision=0,
            created_at=version.created_at,
        )
    )
    registry.save_version(version)
    release = registry.append_release(
        AgentRelease(
            release_id=AgentReleaseId(uuid4()),
            definition_id=version.definition_id,
            version_id=version.version_id,
            authority_issuer=version.authority_issuer,
            namespace_id=version.namespace_id,
            environment=approval.scope.environment,
            status=AgentReleaseStatus.PUBLISHED,
            revision=1,
            definition_digest=version.definition_digest,
            actor_ref="fixture-native-publisher",
            effective_at=datetime.now(UTC),
        )
    )
    candidate = {
        "definition_id": str(version.definition_id),
        "version_id": str(version.version_id),
        "release_id": str(release.release_id),
        "release_revision": release.revision,
        "definition_digest": version.definition_digest,
        "bundle_digest": assembly.bundle.bundle_digest,
    }
    headers = {
        "Authorization": "Bearer " + TOKEN,
        "X-Runtime-Deployment": approval.scope.deployment_id,
        "X-Runtime-Audience": approval.audience,
        "X-Runtime-Product": approval.scope.product_id,
        "X-Runtime-Environment": approval.scope.environment,
        "X-Runtime-Trust-Revision": "1",
        "X-Runtime-Gate-Contract": CONTRACT_DIGEST,
    }
    app = FastAPI()
    register_runtime_gates(app, cfg, approval.scope.namespace_id)
    monkeypatch.setenv("BUNDLE_MODEL_KEY", "isolated-fixture-value")
    with TestClient(app) as client:
        yield SimpleNamespace(
            dsn=host_management_dsn,
            cfg=cfg,
            approval=approval,
            store=store,
            version=version,
            release=release,
            candidate=candidate,
            headers=headers,
            client=client,
            path=path,
            value=value,
        )


def command(action="assess", revision=0, **extra):
    return {"operation_id": str(uuid4()), "action": action, "expected_revision": revision, **extra}


def test_original_get_worker_qualification_expiry_and_no_replay(gate):
    g = gate
    c = g.client
    body = command(candidate=g.candidate)
    first = c.post(PATH, headers=g.headers, json=body)
    assert first.status_code == 200, first.text
    record_response(first, "CommandResponse")
    assert c.post(PATH, headers=g.headers, json=body).status_code == 409
    hdr = {**g.headers, "X-Runtime-Operation": body["operation_id"]}
    observed = c.get(PATH, headers=hdr)
    assert not observed.json()["qualifiedWorkerObserved"]
    record_response(observed, "ObservationResponse")
    worker = RuntimeGateWorker(g.cfg, g.approval.scope.namespace_id)
    from unittest.mock import MagicMock

    from zebra_agent_worker.worker_loop_service import WorkerLoopService

    loop = WorkerLoopService(
        projection_store=MagicMock(), execution_service=MagicMock(), runtime_gates=worker
    )
    loop.maintenance_once(worker_id="gate-worker", batch_size=1, lease_ttl_seconds=30)
    worker._future.result(timeout=5)
    observed = c.get(PATH, headers=hdr)
    assert observed.status_code == 200, observed.text
    assert observed.json()["qualifiedWorkerObserved"], observed.json()
    record_response(observed, "ObservationResponse")
    assert not observed.json()["safeToStop"] and not observed.json()["activationAuthorized"]
    # A separately opened replica reads exactly the original receipt, without dispatch.
    replica = RuntimeGateStore(g.dsn, g.approval.scope, g.approval.trust)
    assert replica.read(body["operation_id"])["original"] == first.json()["original"]
    loop.drain()
    after = c.get(PATH, headers=hdr)
    assert not after.json()["qualifiedWorkerObserved"]
    record_response(after, "ObservationResponse")
    incompatible = RuntimeGateWorker(g.cfg, g.approval.scope.namespace_id)
    incompatible.settings = replace(g.cfg, host_tool_endpoint="https://different.example")
    incompatible.tick()
    incompatible._future.result(timeout=5)
    assert not c.get(PATH, headers=hdr).json()["qualifiedWorkerObserved"]
    incompatible.close()
    with psycopg.connect(g.dsn) as db:
        with pytest.raises(psycopg.Error):
            db.execute(
                "DELETE FROM runtime_gate_operations WHERE deployment_namespace=%s",
                (g.approval.scope.namespace_id,),
            )


def test_drain_gate_cas_and_raw_legacy_event_fence(gate):
    g = gate

    def change(body):
        return g.client.post(PATH, headers=g.headers, json=body).status_code

    with ThreadPoolExecutor(2) as pool:
        codes = list(pool.map(change, [command("drain"), command("drain")]))
    assert sorted(codes) == [200, 409], codes
    observed = g.client.get(PATH, headers=g.headers).json()
    assert observed["admission"] == "draining" and observed["executionQuiescent"]
    from pathlib import Path

    from agent_core.application import SessionBootstrapCommand, SessionBootstrapService
    from agent_storage import PostgresEventStore

    boot = SessionBootstrapService().build(
        SessionBootstrapCommand(
            title="blocked", user_input="no run", workspace_root=Path("/tmp/owned-gate-fixture")
        )
    )
    events = PostgresEventStore(g.dsn, deployment_namespace=g.approval.scope.namespace_id)
    with pytest.raises(psycopg.Error, match="draining"):
        events.append(boot.events[0])
    reopened = g.client.post(PATH, headers=g.headers, json=command("open", 1))
    assert reopened.status_code == 200, reopened.text
    events.append(boot.events[0])
    # Missing projection is explicitly unproven, never silently no active Tasks.
    assert g.client.get(PATH, headers=g.headers).json()["blockers"]["projection_lag"] == 1


def test_http_scope_body_current_approval_and_exact_candidate(gate):
    g = gate
    c = g.client
    assert c.get(PATH).status_code == 401
    assert c.get(PATH, headers={**g.headers, "X-Runtime-Product": "foreign"}).status_code == 403
    assert c.get(PATH + "?ready=true", headers=g.headers).status_code == 400
    assert c.put(PATH, headers=g.headers).status_code == 405
    assert (
        c.post(
            PATH, headers=g.headers, json={**command(candidate=g.candidate), "workerReady": True}
        ).status_code
        == 400
    )
    assert (
        c.post(
            PATH,
            headers=g.headers,
            json=command(candidate={**g.candidate, "release_id": str(uuid4())}),
        ).status_code
        == 400
    )
    assert (
        c.post(
            PATH, headers=g.headers, json=command(candidate=g.candidate, revision=True)
        ).status_code
        == 400
    )
    assert (
        c.get(PATH, headers={**g.headers, "X-Runtime-Operation": str(uuid4())}).status_code == 404
    )
    body = command("drain")
    assert c.post(PATH, headers=g.headers, json=body).status_code == 200
    rotated = {**g.value, "trust_revision": 2}
    g.path.write_text(json.dumps(rotated))
    g.path.chmod(0o600)
    h = {**g.headers, "X-Runtime-Trust-Revision": "2"}
    assert c.get(PATH, headers=h).status_code == 403  # File alone cannot rotate DB approval.
    a = load_runtime_gate_approval(str(g.path), g.approval.scope.namespace_id)
    HostManagementStore(g.dsn, deployment_namespace=g.approval.scope.namespace_id).approve(
        a.trust, 1
    )
    recovered = c.get(PATH, headers={**h, "X-Runtime-Operation": body["operation_id"]})
    assert recovered.status_code == 200 and recovered.json()["original"]["trustRevision"] == 1


def test_old_bound_task_compatibility_and_original_recovery_stays_frozen(gate):
    from pathlib import Path

    from agent_core.application import SessionBootstrapCommand, SessionBootstrapService
    from agent_core.domain.bundle_definition import snapshot_from_release
    from agent_storage import PostgresEventStore, PostgresProjectionStore

    g = gate
    snapshot = snapshot_from_release(
        release=g.release, version=g.version, resolved_at=g.release.effective_at
    )
    boot = SessionBootstrapService().build(
        SessionBootstrapCommand(
            title="old bound task",
            user_input="no model call",
            workspace_root=Path("/tmp/owned-gate"),
            definition_snapshot=snapshot,
        )
    )
    events = PostgresEventStore(g.dsn, deployment_namespace=g.approval.scope.namespace_id)
    projections = PostgresProjectionStore(g.dsn, deployment_namespace=g.approval.scope.namespace_id)
    first_event = boot.events[0].model_copy(
        update={"idempotency_key": "gate-original-" + uuid4().hex}
    )
    for event in (first_event, *boot.events[1:]):
        events.append(event)
    projections.save_session(boot.session)
    body = command(candidate=g.candidate)
    assert g.client.post(PATH, headers=g.headers, json=body).status_code == 200
    hdr = {**g.headers, "X-Runtime-Operation": body["operation_id"]}
    worker = RuntimeGateWorker(g.cfg, g.approval.scope.namespace_id)
    worker.tick()
    worker._future.result(timeout=5)
    observed = g.client.get(PATH, headers=hdr).json()
    assert observed["blockers"]["active_sessions"] == 1
    assert observed["qualifiedWorkerObserved"], observed
    before = observed["original"]
    assert g.client.post(PATH, headers=g.headers, json=command("drain")).status_code == 200
    # Existing identical events are observations/replays, not a new admission.
    events.append(first_event)
    current = g.client.get(PATH, headers=hdr).json()
    assert not current["executionQuiescent"] and current["original"] == before
    # Gate revision change invalidates old Worker observations until actual recheck.
    assert not current["qualifiedWorkerObserved"]
    worker.next_tick = 0
    worker.tick()
    worker._future.result(timeout=5)
    assert g.client.get(PATH, headers=hdr).json()["qualifiedWorkerObserved"]
    # Caller cannot use a fresh user Run/resume during drain; control remains usable.
    from agent_core.contracts import SessionCommand, SessionCommandKind
    from agent_core.domain.events import EventActor, EventType, SessionEvent

    def accepted(kind, key):
        cmd = SessionCommand(
            session_id=boot.session.session_id,
            kind=kind,
            expected_revision=boot.session.current_sequence,
            idempotency_key=key,
        )
        return SessionEvent.create(
            session_id=boot.session.session_id,
            sequence=boot.session.current_sequence + 1,
            event_type=EventType.SESSION_COMMAND_ACCEPTED,
            actor=EventActor.HARNESS,
            payload=cmd.event_payload(),
        )

    with pytest.raises(psycopg.Error, match="draining"):
        events.append(accepted(SessionCommandKind.RUN, "fresh-business-intent"))
    events.append(accepted(SessionCommandKind.CANCEL, "cancel-existing"))
    worker.close()


def test_expired_unreleased_lease_and_contract_header_are_not_drain_proof(gate):
    from datetime import timedelta

    from agent_core.domain.identifiers import SessionId
    from agent_storage import PostgresLeaseStore

    g = gate
    assert (
        g.client.post(
            PATH,
            headers={**g.headers, "X-Runtime-Gate-Contract": "sha256:" + "0" * 64},
            json=command("drain"),
        ).status_code
        == 409
    )
    lease_store = PostgresLeaseStore(g.dsn, deployment_namespace=g.approval.scope.namespace_id)
    lease = lease_store.acquire(
        SessionId(uuid4()), owner_instance_id="unobserved-worker", ttl=timedelta(seconds=30)
    )
    # Simulate natural expiry without claiming termination or altering original receipts.
    with psycopg.connect(g.dsn) as db:
        db.execute(
            """UPDATE worker_leases SET acquired_at=clock_timestamp()-interval '50 seconds',
 heartbeat_at=clock_timestamp()-interval '40 seconds',
 expires_at=clock_timestamp()-interval '10 seconds' WHERE deployment_namespace=%s""",
            (g.approval.scope.namespace_id,),
        )
    assert g.client.post(PATH, headers=g.headers, json=command("drain")).status_code == 200
    facts = g.client.get(PATH, headers=g.headers).json()
    assert facts["blockers"]["unreleased_leases"] == 1 and not facts["executionQuiescent"]
    assert facts["admission"] == "draining" and facts["safeToStop"] is False
    assert lease.fence is not None


def _independent_gate_reader(cfg, namespace, headers, operation, pipe):
    app = FastAPI()
    register_runtime_gates(app, cfg, namespace)
    with TestClient(app) as client:
        response = client.get(PATH, headers={**headers, "X-Runtime-Operation": operation})
        pipe.send((response.status_code, response.json()))
    pipe.close()


def test_unknown_original_recovered_by_independent_api_process(gate):
    import multiprocessing

    g = gate
    body = command("drain")
    original = g.client.post(PATH, headers=g.headers, json=body)
    assert original.status_code == 200
    context = multiprocessing.get_context("spawn")
    receiver, sender = context.Pipe(duplex=False)
    child = context.Process(
        target=_independent_gate_reader,
        args=(g.cfg, g.approval.scope.namespace_id, g.headers, body["operation_id"], sender),
    )
    child.start()
    sender.close()
    try:
        assert receiver.poll(15), "independent original GET timed out"
        status, read = receiver.recv()
        child.join(10)
        assert child.exitcode == 0 and status == 200
        assert read["original"] == original.json()["original"]
        assert read["admission"] == "draining"
    finally:
        if child.is_alive():
            child.terminate()
            child.join(5)
        receiver.close()


def test_engine_preflight_failure_cannot_publish_compatibility(gate, monkeypatch):
    from agent_core.ports.runtime import RuntimeCapabilityError

    g = gate
    body = command(candidate=g.candidate)
    assert g.client.post(PATH, headers=g.headers, json=body).status_code == 200

    def unavailable(_):
        raise RuntimeCapabilityError("fixture unavailable")

    monkeypatch.setattr("zebra_agent_worker.runtime_gates.check_runtime", unavailable)
    worker = RuntimeGateWorker(g.cfg, g.approval.scope.namespace_id)
    try:
        worker.tick()
        worker._future.result(timeout=5)
        observed = g.client.get(
            PATH, headers={**g.headers, "X-Runtime-Operation": body["operation_id"]}
        ).json()
        assert not observed["qualifiedWorkerObserved"]
        assert observed["checks"]["runtimeEngine"] == "unproven"
    finally:
        worker.close()


def test_known_shared_namespace_blocks_drain_without_hiding_originals(gate):
    g = gate
    original = command(candidate=g.candidate)
    assert g.client.post(PATH, headers=g.headers, json=original).status_code == 200
    foreign = replace(g.approval.trust, host_app_id="other-product", product_id="foreign-product")
    HostManagementStore(g.dsn, deployment_namespace=g.approval.scope.namespace_id).approve(
        foreign, 0
    )
    assert g.client.post(PATH, headers=g.headers, json=command("drain")).status_code == 403
    read = g.client.get(
        PATH, headers={**g.headers, "X-Runtime-Operation": original["operation_id"]}
    )
    assert (
        read.status_code == 200
        and read.json()["original"]["operationId"] == original["operation_id"]
    )
    assert read.json()["blockers"]["scope_conflict"] == 1
    assert not read.json()["qualifiedWorkerObserved"]


def test_retention_reserves_explicit_open_and_original_get(gate):
    g = gate
    # Intentional new read assessments in an empty disposable namespace, no Task/model replay.
    for _ in range(126):
        r = g.client.post(PATH, headers=g.headers, json=command(candidate=g.candidate))
        assert r.status_code == 200, r.text
    drain = command("drain")
    assert g.client.post(PATH, headers=g.headers, json=drain).status_code == 200
    assert (
        g.client.post(
            PATH, headers=g.headers, json=command(candidate=g.candidate, revision=1)
        ).status_code
        == 429
    )
    assert g.client.post(PATH, headers=g.headers, json=command("open", 1)).status_code == 200
    assert g.client.post(PATH, headers=g.headers, json=command("drain", 2)).status_code == 429
    read = g.client.get(PATH, headers={**g.headers, "X-Runtime-Operation": drain["operation_id"]})
    assert read.status_code == 200 and read.json()["admission"] == "open"
    assert read.json()["original"]["admission"] == "draining"
