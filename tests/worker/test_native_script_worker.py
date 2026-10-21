"""Owned PostgreSQL + real Worker + Seatbelt + deterministic provider; no production I/O."""
# ruff: noqa: F811

import json
import sys
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from unittest.mock import Mock
from uuid import uuid4

import httpx
import pytest
from agent_core.application import SessionBootstrapCommand, SessionBootstrapService
from agent_core.application.workspace_projection import rebuild_workspace
from agent_core.domain.bundle_definition import snapshot_from_version
from agent_core.domain.cloud_scope import OpaqueAuthorityScope
from agent_core.domain.events import EventType
from agent_core.domain.host_authority import HostContextEnvelope
from agent_core.domain.sessions import SessionStatus
from agent_core.domain.task_bindings import TaskBindingSnapshot, host_context_digest
from agent_core.ports.task_admission_transaction import TaskAdmissionRequest
from agent_storage import apply_postgres_migrations, bootstrap_control_plane_epoch
from agent_storage.postgres.host_auth import HostRegistryRecord, PostgresHostAuthorityStore
from agent_storage.postgres.task_admission import PostgresTaskAdmissionTransaction
from agent_storage.postgres_composition import postgres_control_plane_stores
from zebra_agent_worker import (
    SessionClaimService,
    SessionExecutionService,
    SessionRecoveryService,
    SessionResumeService,
)
from zebra_agent_worker.model_call_index import ModelCallIndexer
from zebra_agent_worker.tool_run_index import ToolRunIndexer

from tests.agent_core.test_native_script_binding import (
    assembly_and_config,
    binding,
    script,
    version,
)
from tests.agent_storage.test_bundle_definition_postgres import (
    raw_bundle_dsn as owned_dsn,  # noqa: F401
)
from tests.agent_storage.test_command_wakeup import _command
from tests.test_bundle_assembly import settings


@pytest.fixture(scope="module")
def script_dsn(owned_dsn):
    apply_postgres_migrations(owned_dsn)
    return owned_dsn


def setup(script_dsn, tmp_path, *, verifier=False, tool_source=None):
    configured = settings()
    configured = replace(
        configured,
        database_url=str(tmp_path / "aux.db"),
        runtime=replace(
            configured.runtime, runtime_class="os-sandbox", image="native@sha256:" + "a" * 64
        ),
    )
    rejected = "def execute(arguments):\n    return {'passed': False}\n"
    sources = [
        script("tool", tool_source),
        script("context"),
        script("verifier", rejected if verifier else None),
    ]
    bindings = [
        binding("tool", tool_source),
        binding("context"),
        binding("verifier", rejected if verifier else None),
    ]
    assembly, configured, catalog = assembly_and_config(
        tmp_path, configured, bindings=bindings, sources=sources
    )
    frozen = version(assembly)
    snapshot = snapshot_from_version(version=frozen, resolved_at=datetime.now(UTC))
    scope = assembly.bundle.manifest.scope
    now = datetime.now(UTC)
    context = HostContextEnvelope(
        grant_id=str(uuid4()),
        host_app_id="business",
        namespace_id=scope.namespace_id,
        workspace_ref="workspace-a",
        resource_refs=({"type": "principal", "id": "user-a"}, {"type": "thread", "id": "thread-a"}),
        scopes=("agent.run", "native.read"),
        limits={"max_runtime_seconds": 600, "max_model_tokens": 200000, "max_artifact_bytes": 1024},
        origin=scope.authority_issuer,
        policy_version="test-v1",
        expires_at=now + timedelta(minutes=10),
    )
    boot = SessionBootstrapService().build(
        SessionBootstrapCommand(
            title="Bound native scripts",
            user_input="Use the native tool once then reply.",
            workspace_root=tmp_path,
            definition_snapshot=snapshot,
            host_context=context,
            network_profile="none",
        )
    )
    binding_value = TaskBindingSnapshot(
        task_id=str(boot.session.session_id),
        binding_revision=1,
        bound_at=now,
        zebra_policy_digest="a" * 64,
        effective_capabilities=frozenset({"agent.execute"}),
        agent_capability_ceiling={
            "definition_snapshot_digest": snapshot.snapshot_digest,
            "capability_profile_ref": "test@1",
            "capabilities": ["agent.execute"],
            "resolved_at": now,
        },
        host_capability={
            "host_app_id": context.host_app_id,
            "authority_issuer": scope.authority_issuer,
            "namespace_id": scope.namespace_id,
            "grant_digest": host_context_digest(context),
            "grant_expires_at": context.expires_at,
            "connector_id": "business",
            "connector_profile_revision": 1,
            "connector_profile_digest": "c" * 64,
            "manifest_digest": "0" * 64,
            "capabilities": ["agent.execute"],
            "resource_binding_digest": "e" * 64,
            "bound_at": now,
            "host_context": context,
        },
    )
    namespace = "native-script-" + uuid4().hex[:12]
    bootstrap_control_plane_epoch(script_dsn, deployment_namespace=namespace)
    PostgresTaskAdmissionTransaction(script_dsn, deployment_namespace=namespace).admit(
        TaskAdmissionRequest(
            events=tuple(boot.events),
            session=boot.session,
            workspace=rebuild_workspace(list(boot.events)),
            binding=binding_value,
        )
    )
    from agent_storage import PostgresEventStore

    command = _command(
        boot.session.session_id, sequence=boot.events[-1].sequence + 1, key=str(uuid4())
    )
    command = command.model_copy(
        update={"payload": command.payload | {"payload": {"run_id": str(uuid4())}}}
    )
    PostgresEventStore(script_dsn, deployment_namespace=namespace).append(command)
    host_store = PostgresHostAuthorityStore(script_dsn, deployment_namespace=namespace)
    record = HostRegistryRecord(
        host_app_id=context.host_app_id,
        namespace_id=context.namespace_id,
        issuer=scope.authority_issuer,
        audience="native-test",
        jwks_uri=scope.authority_issuer + "/jwks",
        allowed_origins=(context.origin,),
        algorithms=("RS256",),
        policy_version=context.policy_version,
    )
    host_store.upsert_registry(record)
    opaque = OpaqueAuthorityScope(
        authority_issuer=scope.authority_issuer, namespace_id=scope.namespace_id
    )
    stores = postgres_control_plane_stores(
        script_dsn,
        deployment_namespace=namespace,
        memory_cursor_signing_key=b"x" * 32,
        artifact_objects=Mock(),
        history_scope=opaque,
        continuation_scope=opaque,
    )
    recovery = SessionRecoveryService(
        stores.events,
        stores.sessions,
        stores.workspaces,
        worker_projection_transaction=stores.workspaces,
        deployment_namespace=namespace,
        model_call_indexer=ModelCallIndexer(stores.model_calls),
        tool_run_indexer=ToolRunIndexer(stores.tool_runs),
        session_recovery_store=stores.session_recovery,
    )
    claims = SessionClaimService(stores.leases, recovery)
    return configured, stores, claims, binding_value, host_store, record, catalog


def provider(bodies):
    def respond(request):
        body = json.loads(request.content)
        bodies.append(body)
        used = any(m["role"] == "tool" for m in body["messages"])
        if body["stream"]:
            delta = (
                {"content": "Checked answer."}
                if used
                else {
                    "tool_calls": [
                        {
                            "index": 0,
                            "id": "native-call-1",
                            "type": "function",
                            "function": {"name": "native__tool", "arguments": '{"query":"hello"}'},
                        }
                    ]
                }
            )
            frame = {"choices": [{"index": 0, "delta": delta, "finish_reason": None}]}
            finish = {
                "choices": [
                    {"index": 0, "delta": {}, "finish_reason": "stop" if used else "tool_calls"}
                ]
            }
            return httpx.Response(
                200,
                headers={"content-type": "text/event-stream"},
                text="data: "
                + json.dumps(frame)
                + "\n\ndata: "
                + json.dumps(finish)
                + "\n\ndata: [DONE]\n\n",
            )
        return httpx.Response(
            200,
            json={
                "choices": [
                    {"message": {"role": "assistant", "content": "Title"}, "finish_reason": "stop"}
                ]
            },
        )

    return httpx.Client(transport=httpx.MockTransport(respond))


def worker(configured, stores, claims, binding_value, client, tmp_path):
    service = SessionExecutionService(
        database_path=tmp_path / "aux.db",
        claim_service=claims,
        resume_service=SessionResumeService(claims),
        settings=configured,
        stores=stores,
        worker_projection_transaction=stores.workspaces,
        deployment_namespace=stores.deployment_namespace,
        task_binding_loader=lambda _: binding_value,
        model_http_client=client,
    )
    from agent_storage import SQLiteEffectLedger, SQLiteProviderContinuationStore

    service._provider_continuation_store = SQLiteProviderContinuationStore(tmp_path / "provider.db")
    service._effect_ledger = SQLiteEffectLedger(tmp_path / "effects.db")
    return service


@pytest.mark.skipif(sys.platform != "darwin", reason="actual native Seatbelt worker proof")
@pytest.mark.parametrize("rejected", [False, True])
def test_actual_worker_three_kinds_and_verifier_only_narrows(
    script_dsn, tmp_path, monkeypatch, rejected
):
    configured, stores, claims, bound, _, _, _ = setup(script_dsn, tmp_path, verifier=rejected)
    monkeypatch.setenv("BUNDLE_MODEL_KEY", "private-test-key")
    bodies = []
    with provider(bodies) as client:
        result = worker(configured, stores, claims, bound, client, tmp_path).execute_session(
            __import__("uuid").UUID(bound.task_id), worker_id="native-worker"
        )
    assert result.session.status is (SessionStatus.FAILED if rejected else SessionStatus.COMPLETED)
    events = stores.events.list_for_session(result.session.session_id)
    completed = [
        e.payload
        for e in events
        if e.event_type is EventType.NATIVE_SCRIPT_INVOCATION and e.payload["phase"] == "completed"
    ]
    assert len(completed) == 3
    assert sum(e.event_type is EventType.ANSWER_COMMITTED for e in events) == (0 if rejected else 1)
    assert all(e["observation"]["status"] == "succeeded" for e in completed)
    assert any(
        "hello" in json.dumps(body["messages"])
        and "Untrusted native script" in json.dumps(body["messages"])
        for body in bodies
    )
    assert any(
        m["role"] == "tool" and "hello" in m["content"] for b in bodies for m in b["messages"]
    )
    assert "private-test-key" not in json.dumps([e.payload for e in events])
    assert not any("coverage_certificate" in e.payload for e in events)


def native_parts(configured, stores, claims, bound, tmp_path, *, owner="native-owner"):
    from uuid import UUID

    from agent_core.domain.leases import LeaseLostError
    from zebra_agent_worker.native_scripts import prepare_native_scripts
    from zebra_agent_worker.task_recovery import recover_task

    claimed = claims.claim_session(
        UUID(bound.task_id), worker_id=owner, claimed_at=datetime.now(UTC), lease_ttl_seconds=60
    )

    def check():
        current = stores.leases.get(claimed.lease.session_id)
        if current is None or current.fence != claimed.lease.fence:
            raise LeaseLostError("native test lost lease")

    service = worker(configured, stores, claims, bound, None, tmp_path)
    recorder = service._projection_recorder_factory.build(
        session=claimed.recovery.session,
        workspace=claimed.recovery.workspace,
        lease=claimed.lease,
        ownership_check=check,
    )
    task = recover_task(
        stores.events.list_for_session(claimed.lease.session_id),
        workspace=recorder.workspace,
        fallback_title=recorder.session.title,
        attachment_reader=stores.artifact_payload_reader,
    )
    tools = prepare_native_scripts(
        settings=configured,
        database_path=tmp_path / "aux.db",
        task=task,
        binding=bound,
        events=stores.events,
        recorder=lambda: recorder,
        instance_factory=None,
        attempt_number=1,
    )
    return tools, recorder, claimed.lease


def test_postgres_v3_registry_survives_independent_reader(script_dsn, tmp_path):
    from agent_storage.postgres.agent_registry import PostgresAgentRegistry

    from tests.agent_storage.test_bundle_definition_postgres import seed

    assembly, _, _ = assembly_and_config(tmp_path)
    value = version(assembly)
    registry = PostgresAgentRegistry(script_dsn, deployment_namespace="native-v3-test")
    seed(registry, value)
    read = PostgresAgentRegistry(script_dsn, deployment_namespace="native-v3-test").get_version(
        value.scope, value.version_id
    )
    assert read == value
    assert read.runtime_assembly.native_scripts == assembly.native_scripts


@pytest.mark.skipif(sys.platform != "darwin", reason="actual native Seatbelt journal proof")
def test_postgres_unknown_terminal_commit_replays_without_runner(script_dsn, tmp_path, monkeypatch):
    configured, stores, claims, bound, _, _, _ = setup(script_dsn, tmp_path)
    monkeypatch.setenv("BUNDLE_MODEL_KEY", "test-only")
    tools, recorder, lease = native_parts(configured, stores, claims, bound, tmp_path)
    journal = tools.service._journal

    class LostAck:
        def read(self, invocation_id):
            return journal.read(invocation_id)

        def append(self, event):
            journal.append(event)
            if event.phase == "completed":
                raise TimeoutError("owned lost commit ACK")

    tools.service._journal = LostAck()
    with pytest.raises(TimeoutError, match="ACK"):
        tools.service.invoke(binding(), {"query": "x"}, logical_id="lost-ack")
    stores.leases.release(lease.session_id, fence=lease.fence)
    recovered, _, _ = native_parts(configured, stores, claims, bound, tmp_path, owner="new-worker")
    monkeypatch.setattr(
        "agent_runtime.native_script_runtime.ScopedNativeScriptRunner.run",
        lambda *a, **k: pytest.fail("terminal replay executed script"),
    )
    result = recovered.service.invoke(binding(), {"query": "x"}, logical_id="lost-ack")
    assert result.output_json == b'{"value":"hello"}'
    records = [
        e
        for e in stores.events.list_for_session(lease.session_id)
        if e.event_type is EventType.NATIVE_SCRIPT_INVOCATION
    ]
    assert [e.payload["phase"] for e in records] == ["started", "completed"]
    from agent_core.domain.runtime_bundle_json import json_digest

    assert (
        json_digest(recorder.worker_mutation_authority.lease_fence.model_dump(mode="json"))
        != recovered.service.owner_fence
    )


@pytest.mark.skipif(sys.platform != "darwin", reason="actual native Seatbelt journal proof")
def test_restart_in_an_independent_process_replays_postgres_receipt(
    script_dsn, tmp_path, monkeypatch
):
    import subprocess

    configured, stores, claims, bound, _, _, _ = setup(script_dsn, tmp_path)
    monkeypatch.setenv("BUNDLE_MODEL_KEY", "test-only")
    tools, _, lease = native_parts(configured, stores, claims, bound, tmp_path)
    expected = tools.service.invoke(binding(), {"query": "x"}, logical_id="process-restart")
    stores.leases.release(lease.session_id, fence=lease.fence)
    payload = {
        "dsn": script_dsn,
        "namespace": stores.deployment_namespace,
        "binding": bound.model_dump(mode="json"),
        "catalog": configured.runtime_bundle_config,
        "snapshot_digest": tools.service.snapshot_digest,
    }
    result = subprocess.run(
        [
            sys.executable,
            "-c",
            "from tests.worker.test_native_script_worker import replay_probe; replay_probe()",
        ],
        input=json.dumps(payload),
        text=True,
        capture_output=True,
        timeout=15,
        check=True,
    )
    assert json.loads(result.stdout) == {
        "output": expected.output_json.decode(),
        "owner": "new-process",
    }
    records = [
        e
        for e in stores.events.list_for_session(lease.session_id)
        if e.event_type is EventType.NATIVE_SCRIPT_INVOCATION
    ]
    assert len(records) == 2


def replay_probe():
    from uuid import UUID

    from agent_core.application.native_script import NativeScriptInvocationService
    from agent_core.domain.runtime_bundle_json import json_digest
    from agent_runtime.native_script_journal import EventScriptJournal
    from agent_storage import PostgresEventStore, PostgresLeaseStore
    from agent_storage.postgres.native_script_authority import (
        NativeScriptAuthority,
        PostgresScriptJournal,
    )
    from zebra_agent_config.bundle_settings import load_execution_catalog

    data = json.load(sys.stdin)
    bound = TaskBindingSnapshot.model_validate(data["binding"])
    events = PostgresEventStore(data["dsn"], deployment_namespace=data["namespace"])
    leases = PostgresLeaseStore(data["dsn"], deployment_namespace=data["namespace"])
    lease = leases.acquire(
        UUID(bound.task_id), owner_instance_id="new-process", ttl=timedelta(seconds=60)
    )
    authority = NativeScriptAuthority(events, bound)

    def check():
        authority.check()
        assert leases.get(lease.session_id).fence == lease.fence

    def forbidden(*args):
        raise AssertionError("terminal replay must not dispatch or append")

    def authorize(item):
        check()
        return load_execution_catalog(data["catalog"]).script_for(item.manifest.digest)

    service = NativeScriptInvocationService(
        task_id=bound.task_id,
        snapshot_digest=data["snapshot_digest"],
        owner_fence=json_digest(lease.fence.model_dump(mode="json")),
        journal=PostgresScriptJournal(
            EventScriptJournal(events, lease.session_id, forbidden, check)
        ),
        authorize=authorize,
        runner=forbidden,
    )
    try:
        result = service.invoke(binding(), {"query": "x"}, logical_id="process-restart")
        print(json.dumps({"output": result.output_json.decode(), "owner": lease.owner_instance_id}))
    finally:
        leases.release(lease.session_id, fence=lease.fence)


@pytest.mark.parametrize("change", ["disabled", "issuer", "policy", "origin", "expired"])
def test_current_host_authority_refuses_dispatch_and_replay(
    script_dsn, tmp_path, monkeypatch, change
):
    from agent_core.application.native_script import NativeScriptUnavailable

    configured, stores, claims, bound, host, record, _ = setup(script_dsn, tmp_path)
    monkeypatch.setenv("BUNDLE_MODEL_KEY", "test-only")
    tools, _, _ = native_parts(configured, stores, claims, bound, tmp_path)
    changes = {
        "disabled": {"active": False},
        "issuer": {"issuer": "https://other.example"},
        "policy": {"policy_version": "changed"},
        "origin": {"allowed_origins": ("https://other.example",)},
    }
    if change == "expired":
        bound = bound.model_copy(
            update={
                "host_capability": bound.host_capability.model_copy(
                    update={"grant_expires_at": datetime.now(UTC) - timedelta(seconds=1)}
                )
            }
        )
        # The same current-Host gate is used by append and replay.
        from agent_storage.postgres.native_script_authority import NativeScriptAuthority

        with pytest.raises(NativeScriptUnavailable):
            NativeScriptAuthority(stores.events, bound).check()
    else:
        host.upsert_registry(replace(record, **changes[change]))
        with pytest.raises(NativeScriptUnavailable, match="HOST_AUTHORITY"):
            tools.service.invoke(binding(), {"query": "x"}, logical_id="revoked")
    assert not [
        e
        for e in stores.events.list_for_session(__import__("uuid").UUID(bound.task_id))
        if e.event_type is EventType.NATIVE_SCRIPT_INVOCATION
    ]


def test_invocation_cannot_use_a_binding_outside_its_frozen_plan(script_dsn, tmp_path):
    from agent_core.application.native_script import NativeScriptUnavailable

    configured, stores, claims, bound, _, _, _ = setup(script_dsn, tmp_path)
    tools, _, lease = native_parts(configured, stores, claims, bound, tmp_path)
    unbound = binding().model_copy(update={"name": "native.unbound"})
    with pytest.raises(NativeScriptUnavailable, match="BINDING_CONFLICT"):
        tools.service.invoke(unbound, {"query": "x"}, logical_id="unbound")
    assert not any(
        e.event_type is EventType.NATIVE_SCRIPT_INVOCATION
        for e in stores.events.list_for_session(lease.session_id)
    )
