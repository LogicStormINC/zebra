"""No-network Host control: pinned identity, revocation and journal boundaries."""

import json
from contextlib import contextmanager
from datetime import UTC, datetime, timedelta
from hashlib import sha256
from types import SimpleNamespace
from unittest.mock import Mock
from uuid import UUID

import httpx
import pytest
from agent_core.domain.execution_authority import (
    ExecutionAuthorityResolutionError,
    ExecutionAuthorityResolutionRequest,
)
from agent_core.domain.host_authority import (
    HostContextEnvelope,
    HostResourceRef,
    HostTechnicalLimits,
)
from agent_core.domain.identifiers import SessionId, new_tool_call_id
from agent_core.domain.tools import ToolCall
from agent_security.host_grant import JwtAlgorithm, VerifiedHostGrant
from zebra_agent_api.session_binding import _build_binding_snapshot
from zebra_agent_config.host_authority_settings import (
    HostExecutionAuthoritySettings,
    load_host_execution_authority,
)
from zebra_agent_worker.bound_execution_authority import BoundHostExecutionAuthorityResolver
from zebra_agent_worker.host_authority_probe import HostAuthorityProbe
from zebra_agent_worker.host_execution_authority import HostExecutionAuthority
from zebra_agent_worker.worker_tool_gateway import WorkerToolGateway


def case(monkeypatch):
    now = datetime.now(UTC)
    task = "11111111-1111-1111-1111-111111111111"
    context = HostContextEnvelope(
        grant_id="control-1",
        host_app_id="example",
        namespace_id="example:team",
        workspace_ref="workspace:one",
        origin="https://host.example",
        resource_refs=tuple(
            HostResourceRef(type=k, id=v)
            for k, v in {
                "thread": "thread-one",
                "run": "run-one",
                "principal": "user-one",
                "company": "company-one",
            }.items()
        ),
        scopes=("agent.run",),
        limits=HostTechnicalLimits(
            max_runtime_seconds=300, max_model_tokens=10000, max_artifact_bytes=1000000
        ),
        expires_at=now + timedelta(minutes=5),
        policy_version="host-native-v2",
    )
    binding = _build_binding_snapshot(
        task,
        host_context=context,
        verified_host_grant=VerifiedHostGrant(
            context, context.grant_id, JwtAlgorithm.RS256, context.origin, "user-one"
        ),
        definition_snapshot_digest="a" * 64,
    )
    host = binding.host_capability
    registry = Mock()
    registry.resolve_binding.return_value = SimpleNamespace(
        active=True,
        connector_id=host.connector_id,
        profile_revision=host.connector_profile_revision,
    )
    registry.get_profile.return_value = SimpleNamespace(
        profile_digest=host.connector_profile_digest, workload_identity_ref="worker-example"
    )
    identity = dict(
        task_id=task,
        thread_id="thread-one",
        run_id="run-one",
        principal="user-one",
        workspace_ref="workspace:one",
        company="company-one",
    )
    payload = dict(
        decision="allowed",
        identity=identity,
        metadata_digest=sha256(
            json.dumps(identity, sort_keys=True, separators=(",", ":")).encode()
        ).hexdigest(),
        expires_at=(now + timedelta(minutes=2)).isoformat(),
    )
    pinned = Mock(shared_secret="private-test-secret")
    from agent_core.domain.tools import ToolCallStatus, ToolResult

    def invoke(call, *args, **kwargs):
        return ToolResult(
            tool_call_id=call.tool_call_id,
            name=call.name,
            status=ToolCallStatus.EXECUTED,
            output=json.dumps(payload),
        )

    pinned.invoke.side_effect = invoke
    monkeypatch.setattr(
        "zebra_agent_worker.host_authority_probe.resolve_pinned_gateway", lambda *args: pinned
    )
    client = httpx.Client(transport=httpx.MockTransport(lambda _: pytest.fail("unexpected HTTP")))
    probe = HostAuthorityProbe(
        binding,
        registry,
        Mock(),
        task_id=task,
        settings=HostExecutionAuthoritySettings(enabled=True),
        client=client,
    )
    resolver = BoundHostExecutionAuthorityResolver(binding)
    snapshot = resolver.resolve_for_attempt(
        ExecutionAuthorityResolutionRequest(
            session_id=SessionId(UUID(task)),
            attempt_number=1,
            scope=resolver.scope,
            validated_at=now,
        )
    )
    return probe, payload, registry, snapshot, pinned


@pytest.mark.parametrize(
    "change", ["principal", "company", "digest", "expiry", "unknown", "revoked"]
)
def test_probe_refuses_identity_expiry_and_revocation(monkeypatch, change):
    probe, payload, registry, _, pinned = case(monkeypatch)
    if change in {"principal", "company"}:
        payload["identity"][change] = "foreign"
    elif change == "digest":
        payload["metadata_digest"] = "0" * 64
    elif change == "expiry":
        payload["expires_at"] = (datetime.now(UTC) + timedelta(hours=1)).isoformat()
    elif change == "unknown":
        payload["identity"]["unbound"] = "foreign"
    elif change == "revoked":
        registry.resolve_binding.return_value.active = False
    with pytest.raises(ExecutionAuthorityResolutionError):
        probe.check()
    probe.client.close()


def test_probe_is_fresh_and_injected_client_remains_open(monkeypatch):
    probe, _, _, _, pinned = case(monkeypatch)
    probe.check()
    probe.check()
    assert pinned.invoke.call_count == 2
    assert not probe.client.is_closed
    probe.client.close()


def test_guard_narrows_chain_and_latches_revocation(monkeypatch):
    probe, _, registry, prior, _ = case(monkeypatch)
    events = []

    @contextmanager
    def mutation():
        yield

    recorder = SimpleNamespace(
        mutation=mutation,
        require_active_execution=Mock(),
        session=SimpleNamespace(session_id=SessionId(UUID(probe.binding.task_id))),
        append=lambda *args: events.append(args),
    )
    guard = HostExecutionAuthority(probe)
    guard._prior = prior
    guard._recorder = lambda: recorder
    guard.check("context")
    assert guard._prior.expires_at < prior.expires_at
    assert events[0][2]["prior_snapshot_digest"] == prior.snapshot_digest
    guard.check("tool")
    assert events[1][2]["prior_snapshot_digest"] == events[0][2]["effective_snapshot_digest"]
    registry.resolve_binding.return_value.active = False
    with pytest.raises(ExecutionAuthorityResolutionError):
        guard.check("model")
    registry.resolve_binding.return_value.active = True
    with pytest.raises(ExecutionAuthorityResolutionError):
        guard.check("model")
    assert len(events) == 2
    probe.client.close()


def test_cancel_blocks_probe_and_tool_delegate(monkeypatch):
    probe, _, _, prior, pinned = case(monkeypatch)

    @contextmanager
    def mutation():
        yield

    guard = HostExecutionAuthority(probe)
    guard._prior = prior
    recorder = SimpleNamespace(
        mutation=mutation, require_active_execution=Mock(side_effect=RuntimeError("cancelled"))
    )
    guard._recorder = lambda: recorder
    local = Mock()
    gateway = WorkerToolGateway(local, authority_check=guard.check)
    with pytest.raises(RuntimeError, match="cancelled"):
        gateway.execute(
            ToolCall(
                tool_call_id=new_tool_call_id(),
                created_at=datetime.now(UTC),
                name="files.read",
                arguments={"path": "private"},
            )
        )
    local.execute.assert_not_called()
    pinned.invoke.assert_not_called()
    probe.client.close()


def test_default_disabled_and_strict_opt_in():
    assert not load_host_execution_authority({}).enabled
    with pytest.raises(ValueError):
        load_host_execution_authority({"ZEBRA_HOST_EXECUTION_AUTHORITY_ENABLED": "maybe"})
    assert (
        HostExecutionAuthority.for_execution(
            SimpleNamespace(
                _settings=SimpleNamespace(host_execution_authority=HostExecutionAuthoritySettings())
            ),
            None,
        )
        is None
    )


@pytest.mark.parametrize("drift", [False, True])
def test_child_uses_verified_parent_host_identity_without_expanding_child(monkeypatch, drift):
    from uuid import uuid4

    from agent_core.domain.subagent_delegation import ParentChildLink

    probe, _, registry, _, _ = case(monkeypatch)
    parent = probe.binding
    child_id = uuid4()
    child = parent.model_copy(update={"task_id": str(child_id)})
    link = ParentChildLink(
        root_task_id=UUID(parent.task_id),
        parent_task_id=UUID(parent.task_id),
        child_task_id=child_id,
        delegation_id="a" * 64,
        parent_binding_digest=parent.binding_digest,
        child_binding_digest="0" * 64 if drift else child.binding_digest,
        created_at=datetime.now(UTC),
    )
    store = Mock()
    store.get_link.side_effect = lambda value: link if str(value) == str(child_id) else None
    service = SimpleNamespace(
        _settings=SimpleNamespace(
            host_execution_authority=HostExecutionAuthoritySettings(enabled=True),
            host_tool_shared_secret="test-only",
        ),
        _task_index_store=Mock(),
        _task_binding_loader=lambda identity: child if str(identity) == str(child_id) else parent,
        _egress_registry=registry,
        _delegation_store=store,
    )
    service._task_index_store.task_id_for_session.return_value = child_id
    if drift:
        with pytest.raises(ExecutionAuthorityResolutionError, match="lineage"):
            HostExecutionAuthority.for_execution(service, child_id)
    else:
        guard = HostExecutionAuthority.for_execution(service, child_id)
        assert guard.probe.binding.task_id == str(child_id)
        assert guard.probe.arguments["task_id"] == parent.task_id
        assert guard.probe.binding.effective_capabilities <= parent.effective_capabilities
        guard.probe.check()
    probe.client.close()
