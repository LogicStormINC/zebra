"""Real PostgreSQL child admission/replay keeps Plugin inheritance closed."""

import asyncio
from dataclasses import replace
from uuid import UUID

from agent_core.application import current_turn
from agent_core.application.workspace_projection import rebuild_workspace
from agent_core.domain.context_inheritance import ContextInheritanceMode
from agent_core.domain.events import EventType
from agent_core.domain.identifiers import SessionId
from agent_core.domain.policies import PolicyDecisionType
from agent_core.domain.tool_profiles import ToolProfile
from agent_core.domain.tools import ToolCallStatus
from agent_runtime.research_context import delegate_durable_research, durable_research_contract
from agent_security import LocalPolicyEngine, PolicyProfile
from agent_security.network_profile import parse_network_profile
from agent_storage.postgres.subagent_delegation import PostgresSubagentDelegationStore
from zebra_agent_worker.extension_recovery import recover_turn_extension
from zebra_agent_worker.task_recovery import recover_task
from zebra_agent_worker.tool_gateway_runtime import build_worker_tool_gateway

from tests.cloud_plugins.native_worker import call, recover
from tests.worker.execution.worker_execution_support import _settings


def assert_child_authority(fixture, parent_id, root, *, search_allowed):
    parent = recover(fixture, parent_id)
    assert parent.snapshot.plugins and parent.snapshot.skills and parent.snapshot.mcp
    parent_events = fixture.events.list_for_session(parent_id)
    workspace = rebuild_workspace(parent_events)
    store = PostgresSubagentDelegationStore(fixture.dsn, deployment_namespace=fixture.namespace)
    proposal = call(
        "agent.research", {"objective": "offline child", "delegation_reason": "isolation"}
    )
    arguments = dict(
        objective="offline child",
        delegation_reason="isolation",
        context_mode=ContextInheritanceMode.FRESH,
        context_source=None,
        workspace_root=root,
        delegation_store=store,
        parent_task_id=parent_id,
        parent_binding=parent.task_ceiling.binding,
        max_model_calls=2,
        max_tool_calls=4,
        parent_tool_profile=workspace.tool_profile,
        parent_network_profile=parse_network_profile(
            workspace.network_profile, domain_allowlist=workspace.network_allowlist
        ),
        web_search_endpoint="https://search.example.com/search",
    )
    first = delegate_durable_research(proposal, **arguments)
    second = delegate_durable_research(proposal, **arguments)
    assert first.status is second.status is ToolCallStatus.EXECUTED
    assert first.metadata["child_task_id"] == second.metadata["child_task_id"]
    child_id = SessionId(UUID(first.metadata["child_task_id"]))
    assert child_id != parent_id and second.metadata["replayed"] is True
    events = fixture.events.list_for_session(child_id)
    child_ws = rebuild_workspace(events)
    task = recover_task(events, workspace=child_ws, fallback_title="child", attachment_reader=None)
    ceiling = fixture.snapshots.resolve_task_ceiling(session_id=str(child_id))
    assert ceiling.binding.task_id == str(child_id)
    assert ceiling.binding.binding_digest != parent.task_ceiling.binding.binding_digest
    assert ceiling.binding.agent_capability_ceiling.definition_snapshot_digest == "0" * 64
    assert ceiling.skill_components == () and not task.skill_components and not task.mcp_allowlist
    assert child_ws.policy_profile == "read_only"
    assert child_ws.tool_profile is (
        ToolProfile.RESEARCH_WEB if search_allowed else ToolProfile.RESEARCH
    )
    assert child_ws.network_allowlist == (("search.example.com",) if search_allowed else ())
    turn = current_turn(events)
    assert turn is not None and turn.turn_id != parent.snapshot.turn_id
    scope = parent.scope
    assert not asyncio.run(
        fixture.snapshots.exists(scope=scope, session_id=str(child_id), turn_id=turn.turn_id)
    )
    assert (
        recover_turn_extension(
            store=fixture.snapshots,
            events=events,
            session_id=child_id,
            task_binding=ceiling.binding,
            allow_mcp=True,
            allow_plugins=True,
        )
        is None
    )
    for event in events:
        if event.event_type is EventType.SESSION_COMMAND_ACCEPTED:
            assert not event.payload.get("extension_snapshot_digest")
            assert not event.payload.get("extension_turn_id")
            assert not event.payload.get("payload", {}).get("extension_selection")
    # No VerifiedHostGrant or parent Turn is supplied to the child gateway.
    from unittest.mock import Mock

    from agent_runtime import LocalRuntime

    gateway = build_worker_tool_gateway(
        task,
        settings=replace(
            _settings(root / "unused.sqlite"),
            web_search_endpoint="https://search.example.com/search",
        ),
        model_gateway=Mock(),
        session_history=Mock(),
        session_id=child_id,
        runtime=LocalRuntime(),
        runtime_handle=None,
        local_artifacts=None,
        artifact_payload_reader=None,
        cloud_artifacts=None,
        trusted_local=False,
        durable_delegation=True,
        delegation_store=store,
        parent_task_id=child_id,
        parent_binding=ceiling.binding,
    )
    try:
        names = {tool.name for tool in gateway.model_tools}
        assert ("web.search" in names) is search_allowed
        assert not any(name.startswith(("skills.", "mcp.")) for name in names)
        assert {
            "agent.research",
            "command.run",
            "patch.apply",
            "tests.run",
            "web.fetch",
        }.isdisjoint(names)
        assert gateway.local.effective_skill_components == ()
        assert gateway.local.effective_mcp_tools == ()
        policy = LocalPolicyEngine(
            profile=PolicyProfile.READ_ONLY,
            network_profile=parse_network_profile(
                child_ws.network_profile, domain_allowlist=child_ws.network_allowlist
            ),
            web_search_endpoint="https://search.example.com/search",
        )
        assert (
            policy.evaluate_tool_call(call("web.search", {"query": "offline"})).decision
            is PolicyDecisionType.ALLOW
        ) is search_allowed
        nested = delegate_durable_research(
            proposal,
            **{
                **arguments,
                "parent_task_id": child_id,
                "parent_binding": ceiling.binding,
            },
        )
        assert nested.status is ToolCallStatus.FAILED
        assert nested.metadata["reason"] == "durable_delegation_depth_limit"
    finally:
        gateway.close()
    return {
        "distinct_identity": True,
        "extension_inheritance": "closed",
        "depth": 1,
        "read_only": True,
        "search_allowed": search_allowed,
    }


def test_contract_truthfully_states_closed_plugin_inheritance():
    from agent_tools.contracts import ToolContract

    base = ToolContract(name="agent.research", description="Research", argument_properties={})
    assert (
        "Children do not inherit parent Skills, Plugins, or MCP selections."
        in durable_research_contract(base).description
    )
