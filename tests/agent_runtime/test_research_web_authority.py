"""Search delegation narrows real Worker metadata; all transports stay offline."""

import socket
from dataclasses import replace
from datetime import UTC, datetime
from unittest.mock import Mock
from uuid import UUID, uuid4

import pytest
from agent_core.application.session_bootstrap import (
    SessionBootstrapCommand,
    SessionBootstrapService,
)
from agent_core.application.workspace_projection import rebuild_workspace
from agent_core.domain.context_inheritance import ContextInheritanceMode
from agent_core.domain.identifiers import SessionId, new_tool_call_id
from agent_core.domain.policies import PolicyDecisionType
from agent_core.domain.tool_profiles import ToolProfile, tool_names_for_profile
from agent_core.domain.tools import ToolCall, ToolCallStatus
from agent_core.ports.task_admission_transaction import TaskAdmissionRequest
from agent_runtime import LocalToolGateway
from agent_runtime.research_context import delegate_durable_research, research_search_domains
from agent_security import LocalPolicyEngine, PolicyProfile
from agent_security.network_profile import parse_network_profile
from agent_storage import (
    PostgresEventStore,
    PostgresWorkspaceProjectionStore,
    bootstrap_control_plane_epoch,
)
from agent_storage.postgres.subagent_delegation import PostgresSubagentDelegationStore
from agent_storage.postgres.task_admission import PostgresTaskAdmissionTransaction
from agent_tools.web_search import WebSearchResponse
from zebra_agent_worker.tool_gateway_runtime import build_worker_tool_gateway

from tests.agent_core.test_subagent_delegation_contracts import _parent_binding
from tests.agent_runtime.test_durable_research_run_identity import _delegation_store
from tests.api.test_postgres_host_auth_authorizer import dsn as _isolated_dsn
from tests.api.test_postgres_host_auth_authorizer import postgres_dsn as _postgres_dsn
from tests.worker.execution.worker_execution_support import _settings
from tests.worker.test_cloud_context_materialization import _task

postgres_dsn = _postgres_dsn
research_dsn = _isolated_dsn

ENDPOINT = "https://search.example.com/search"


def _call(*, name, arguments):
    return ToolCall(
        tool_call_id=new_tool_call_id(),
        created_at=datetime.now(UTC),
        name=name,
        arguments=arguments,
    )


@pytest.fixture(autouse=True)
def no_remote_requests(monkeypatch):
    def forbidden(*args, **kwargs):
        raise AssertionError("this regression must not make network requests")

    monkeypatch.setattr(socket, "create_connection", forbidden)
    monkeypatch.setattr(socket, "getaddrinfo", forbidden)


@pytest.mark.parametrize(
    "profile,network,domains,endpoint,allowed",
    [
        ("general", "full-gateway", (), ENDPOINT, True),
        ("coding", "full-gateway", (), ENDPOINT, True),
        ("general", "full-trusted-local", (), ENDPOINT, True),
        ("general", "domain-allowlist", ("search.example.com", "other.example"), ENDPOINT, True),
        ("general", "domain-allowlist", ("other.example",), ENDPOINT, False),
        ("general", "none", (), ENDPOINT, False),
        ("general", "mcp-proxy-only", (), ENDPOINT, False),
        ("general", "setup-only", (), ENDPOINT, False),
        ("general", "git-proxy-only", (), ENDPOINT, False),
        ("research", "full-gateway", (), ENDPOINT, False),
        ("research_coordinator", "full-gateway", (), ENDPOINT, False),
        ("general", "full-gateway", (), None, False),
        ("general", "full-gateway", (), "http://search.example.com", False),
        ("general", "full-gateway", (), "https://127.0.0.1", False),
        ("general", "full-gateway", (), "https://user:secret@search.example.com", False),
    ],
)
def test_search_authority_intersection(profile, network, domains, endpoint, allowed):
    result = research_search_domains(
        ToolProfile(profile),
        parse_network_profile(network, domain_allowlist=domains),
        endpoint,
    )
    assert result == (("search.example.com",) if allowed else ())


def _gateway(tmp_path, task, parent, store, *, pipeline_v2=False):
    return build_worker_tool_gateway(
        task,
        settings=replace(
            _settings(tmp_path / "unused.sqlite"),
            profile="cloud",
            web_search_endpoint=ENDPOINT,
            web_pipeline_v2=pipeline_v2,
        ),
        model_gateway=Mock(),
        session_history=Mock(),
        session_id=uuid4(),
        runtime=Mock(),
        runtime_handle=None,
        local_artifacts=None,
        artifact_payload_reader=None,
        cloud_artifacts=None,
        trusted_local=False,
        durable_delegation=True,
        delegation_store=store,
        parent_task_id=parent.task_id,
        parent_binding=parent,
    )


@pytest.mark.parametrize(
    "network,expected", [("full-gateway", True), ("none", False), ("mcp-proxy-only", False)]
)
@pytest.mark.parametrize("pipeline_v2", [False, True])
def test_real_worker_to_durable_child_and_recovery(tmp_path, network, expected, pipeline_v2):
    parent = _parent_binding()
    store, admissions = _delegation_store()
    task = replace(
        _task(tmp_path),
        tool_profile=ToolProfile.GENERAL,
        network_profile=parse_network_profile(network),
    )
    gateway = _gateway(tmp_path, task, parent, store, pipeline_v2=pipeline_v2)
    call = _call(
        name="agent.research",
        arguments={
            "objective": "Collect independent sources",
            "delegation_reason": "Independent evidence",
        },
    )
    try:
        result = gateway.execute(call)
        assert result.status is ToolCallStatus.EXECUTED
        request, admission = admissions[0]
        ws = rebuild_workspace(list(admission.events))
        assert ws.policy_profile == "read_only"
        assert ws.tool_profile is (ToolProfile.RESEARCH_WEB if expected else ToolProfile.RESEARCH)
        assert ws.network_profile == ("domain-allowlist" if expected else "none")
        assert ws.network_allowlist == (("search.example.com",) if expected else ())
        assert admission.binding.effective_capabilities <= parent.effective_capabilities
        assert set(admission.binding.effective_capabilities) == {"agent.execute", "evidence.read"}
        child = replace(
            task,
            tool_profile=ws.tool_profile,
            policy_profile=ws.policy_profile,
            network_profile=parse_network_profile(
                ws.network_profile, domain_allowlist=ws.network_allowlist
            ),
        )
        recovered = _gateway(tmp_path, child, admission.binding, store, pipeline_v2=pipeline_v2)
        try:
            names = {tool.name for tool in recovered.model_tools}
            assert ("web.search" in names) is expected
            assert {
                "web.fetch",
                "web.crawl",
                "web.extract",
                "agent.research",
                "command.run",
                "patch.apply",
                "tests.run",
            }.isdisjoint(names)
            assert (
                recovered.execute(
                    _call(name="web.fetch", arguments={"url": "https://other.example/"})
                ).status
                is ToolCallStatus.FAILED
            )
        finally:
            recovered.local.close()
        store.get_link.return_value = object()
        blocked = delegate_durable_research(
            call,
            objective="Nested evidence",
            delegation_reason="Nested",
            context_mode=ContextInheritanceMode.FRESH,
            context_source=None,
            workspace_root=tmp_path,
            delegation_store=store,
            parent_task_id=UUID(admission.binding.task_id),
            parent_binding=admission.binding,
            max_model_calls=2,
            max_tool_calls=4,
            parent_tool_profile=ToolProfile.RESEARCH_WEB,
            parent_network_profile=parse_network_profile("full-gateway"),
            web_search_endpoint=ENDPOINT,
        )
        assert blocked.status is ToolCallStatus.FAILED
        assert blocked.metadata["reason"] == "durable_delegation_depth_limit"
        assert len(admissions) == 1
    finally:
        gateway.local.close()


def test_readonly_policy_search_only_and_endpoint_drift():
    profile = parse_network_profile("domain-allowlist", domain_allowlist=("search.example.com",))
    call = _call(name="web.search", arguments={"query": "ordinary query"})
    policy = LocalPolicyEngine(
        profile=PolicyProfile.READ_ONLY, network_profile=profile, web_search_endpoint=ENDPOINT
    )
    assert policy.evaluate_tool_call(call).decision is PolicyDecisionType.ALLOW
    changed = replace(policy, web_search_endpoint="https://other.example/search")
    assert changed.evaluate_tool_call(call).decision is PolicyDecisionType.DENY
    for name in ("command.run", "patch.apply"):
        assert (
            policy.evaluate_tool_call(_call(name=name, arguments={})).decision
            is PolicyDecisionType.DENY
        )
    native = replace(policy, web_pipeline_v2=True)
    auto = call.model_copy(update={"arguments": {"query": "ordinary query", "auto_fetch": True}})
    assert native.evaluate_tool_call(auto).decision is PolicyDecisionType.DENY


def test_default_local_research_unchanged_and_offline_transport(tmp_path):
    transport = Mock()
    transport.execute.return_value = WebSearchResponse(results=(), provider="offline", byte_count=0)
    for profile, expected in ((ToolProfile.RESEARCH, False), (ToolProfile.RESEARCH_WEB, True)):
        gateway = LocalToolGateway(
            tmp_path,
            tool_profile=profile,
            web_search_endpoint=ENDPOINT,
            web_search_transport=transport,
        )
        try:
            assert ("web.search" in {t.name for t in gateway.model_tools}) is expected
            result = gateway.execute(
                _call(name="web.search", arguments={"query": "ordinary query"})
            )
            assert result.status is (ToolCallStatus.EXECUTED if expected else ToolCallStatus.FAILED)
        finally:
            gateway.close()
    assert transport.execute.call_count == 1
    assert tool_names_for_profile(ToolProfile.RESEARCH_WEB) == (
        tool_names_for_profile(ToolProfile.RESEARCH) | {"web.search"}
    )


@pytest.mark.parametrize("network,expected", [("full-gateway", True), ("none", False)])
def test_postgres_child_search_profile_survives_replay(tmp_path, research_dsn, network, expected):
    namespace = f"research-search-{uuid4()}"
    bootstrap_control_plane_epoch(research_dsn, deployment_namespace=namespace)
    bootstrap = SessionBootstrapService().build(
        SessionBootstrapCommand(
            title="Parent",
            user_input="Collect evidence",
            workspace_root=tmp_path,
            tool_profile=ToolProfile.GENERAL,
            network_profile=network,
        )
    )
    parent = _parent_binding().model_copy(update={"task_id": str(bootstrap.session.session_id)})
    PostgresTaskAdmissionTransaction(research_dsn, deployment_namespace=namespace).admit(
        TaskAdmissionRequest(
            events=bootstrap.events,
            session=bootstrap.session,
            workspace=rebuild_workspace(list(bootstrap.events)),
            binding=parent,
        )
    )
    store = PostgresSubagentDelegationStore(research_dsn, deployment_namespace=namespace)
    events = PostgresEventStore(research_dsn, deployment_namespace=namespace)
    workspaces = PostgresWorkspaceProjectionStore(research_dsn, deployment_namespace=namespace)
    task = replace(
        _task(tmp_path),
        tool_profile=ToolProfile.GENERAL,
        network_profile=parse_network_profile(network),
    )
    call = _call(
        name="agent.research",
        arguments={
            "objective": "Collect sources",
            "delegation_reason": "Independent evidence",
        },
    )
    ids = []
    for _ in range(2):
        gateway = _gateway(tmp_path, task, parent, store)
        try:
            result = gateway.execute(call)
            assert result.status is ToolCallStatus.EXECUTED
        finally:
            gateway.close()
        child = SessionId(UUID(result.metadata["child_task_id"]))
        ids.append(child)
        stored = workspaces.get_workspace(child)
        replayed = rebuild_workspace(events.list_for_session(child))
        assert stored is not None
        for ws in (stored, replayed):
            assert ws.policy_profile == "read_only"
            assert ws.tool_profile is (
                ToolProfile.RESEARCH_WEB if expected else ToolProfile.RESEARCH
            )
            assert ws.network_profile == ("domain-allowlist" if expected else "none")
            assert ws.network_allowlist == (("search.example.com",) if expected else ())
    assert ids[0] == ids[1]
