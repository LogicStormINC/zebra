"""Worker catalogs and harness HITL, with no model and a labeled MCP wire seam."""

from __future__ import annotations

import io
import json
from contextlib import contextmanager
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from unittest.mock import Mock, patch

from agent_core.application.approvals import (
    ApprovalDecisionAction,
    ApprovalDecisionCommand,
    ApprovalDecisionService,
)
from agent_core.application.session_projection import rebuild_session
from agent_core.application.workspace_projection import rebuild_workspace
from agent_core.domain.events import EventActor, EventType, SessionEvent
from agent_core.domain.execution_authority import ExecutionAuthorityResolutionRequest
from agent_core.domain.identifiers import new_message_id, new_tool_call_id
from agent_core.domain.messages import MessageRole, SessionMessage
from agent_core.domain.modeling import ModelCompletion
from agent_core.domain.tools import ToolCall
from agent_core.harness.hooks import NoopVerifier
from agent_core.harness.model_step import HarnessModelStep
from agent_core.harness.models import (
    HarnessAttempt,
    HarnessAttemptOutcome,
    HarnessContext,
    HarnessTask,
)
from agent_core.harness.tool_batch import ToolBatchExecutor
from agent_integrations.plugins.publication import PluginPackagePublicationService
from agent_runtime import LocalRuntime
from agent_security import LocalPolicyEngine
from agent_security.mcp_credential_protection import McpCredentialProtector
from agent_security.mcp_credential_release import McpCredentialRelease
from agent_security.mcp_execution_authority import McpWorkerAuthority
from agent_security.network_profile import parse_network_profile
from agent_security.secret_store import LocalSecretStore
from agent_storage.postgres.leases import PostgresLeaseStore
from agent_storage.postgres.mcp_credentials import PostgresMcpCredentialStore
from zebra_agent_worker.approved_continuation import recover_approved_continuation
from zebra_agent_worker.bound_execution_authority import BoundHostExecutionAuthorityResolver
from zebra_agent_worker.extension_recovery import recover_turn_extension
from zebra_agent_worker.task_recovery import recover_task
from zebra_agent_worker.tool_gateway_runtime import build_worker_tool_gateway
from zebra_agent_worker.worker_mcp_catalog import WorkerMcpSource, prepare_worker_mcp
from zebra_agent_worker.worker_plugins import WorkerPluginSource, prepare_worker_plugins
from zebra_agent_worker.worker_skill_catalog import (
    WorkerSkillCatalogSource,
    prepare_worker_skill_catalog,
)

from tests.cloud_plugins.native_fixture import NativeFixture
from tests.worker.execution.worker_execution_support import _settings


def recover(fixture: NativeFixture, session_id, *, allow_plugins=True):
    ceiling = fixture.snapshots.resolve_task_ceiling(session_id=str(session_id))
    return recover_turn_extension(
        store=fixture.snapshots,
        events=fixture.events.list_for_session(session_id),
        session_id=session_id,
        task_binding=ceiling.binding,
        allow_mcp=True,
        allow_plugins=allow_plugins,
    )


def catalogs(fixture: NativeFixture, extension, session_id, root):
    source = WorkerPluginSource(
        fixture.plugins,
        PluginPackagePublicationService(root / "absent", (), fixture.objects, fixture.namespace),
    )
    guard = prepare_worker_plugins(
        extension,
        source=source,
        skills_available=True,
        mcp_available=True,
    )
    skill = prepare_worker_skill_catalog(
        extension,
        deployment_namespace=fixture.namespace,
        source=WorkerSkillCatalogSource(fixture.extensions, fixture.objects),
        plugin_guard=guard,
    )
    leases = PostgresLeaseStore(fixture.dsn, deployment_namespace=fixture.namespace)
    lease = leases.acquire(session_id, owner_instance_id="native-worker", ttl=timedelta(minutes=2))
    credentials = PostgresMcpCredentialStore(
        fixture.dsn,
        deployment_namespace=fixture.namespace,
        task_io_connections=fixture.io,
    )
    release = McpCredentialRelease(
        credentials,
        fixture.snapshots,
        fixture.snapshots,
        McpCredentialProtector(LocalSecretStore(root / "unused-secrets"), "unused", "v1"),
        fixture.namespace,
    )

    def authority(key, turn):
        assert key == session_id and turn == extension.snapshot.turn_id
        # Reload the actual current binding for EVERY MCP frame, as the Worker does.
        ceiling = fixture.snapshots.resolve_task_ceiling(session_id=str(key))
        resolver = BoundHostExecutionAuthorityResolver(ceiling.binding)
        evidence = resolver.resolve_for_attempt(
            ExecutionAuthorityResolutionRequest(
                session_id=key,
                attempt_number=1,
                scope=resolver.scope,
                validated_at=datetime.now(UTC),
            )
        )
        return McpWorkerAuthority(str(key), evidence)

    mcp = prepare_worker_mcp(
        extension,
        source=WorkerMcpSource(fixture.catalogs, credentials, release, leases, authority),
        session_id=session_id,
        fence=lease.fence,
        plugin_guard=guard,
    )
    return skill, mcp, leases, lease


@contextmanager
def protocol_stub():
    """Stub only MCP HTTPS opener and public-DNS check; PG/S3 sockets stay native.

    No real HTTPS/DNS/server interoperability is claimed. The three real MCP
    session frames still pass the fresh Task, lease, component and Plugin guards.
    """
    methods = []

    class Response(io.BytesIO):
        headers = {"Content-Type": "application/json"}

    class Opener:
        def open(self, request, timeout):
            assert request.full_url == "https://mcp.example.com/native"
            assert request.get_header("Authorization") is None
            frame = json.loads(request.data)
            method = frame["method"]
            methods.append(method)
            assert method in {"initialize", "notifications/initialized", "tools/call"}
            if method == "tools/call":
                assert frame["params"] == {
                    "name": "echo",
                    "arguments": {"value": "NATIVE-MCP-PROOF"},
                }
            result = (
                {"protocolVersion": "2025-11-25", "capabilities": {"tools": {}}}
                if method == "initialize"
                else {"content": [{"type": "text", "text": "NATIVE-MCP-PROOF"}]}
            )
            return Response(
                json.dumps({"jsonrpc": "2.0", "id": frame.get("id"), "result": result}).encode()
            )

    with (
        patch("agent_runtime.mcp_http.reject_non_public_resolution", lambda *a, **k: None),
        patch("agent_runtime.mcp_http.urllib.request.build_opener", lambda *a: Opener()),
    ):
        yield methods


def call(name, arguments):
    return ToolCall(
        tool_call_id=new_tool_call_id(),
        name=name,
        arguments=arguments,
        created_at=datetime.now(UTC),
    )


def persist(fixture, session_id, drafts):
    for draft in drafts:
        last = fixture.events.list_for_session(session_id)[-1]
        fixture.events.append(
            SessionEvent.create(
                session_id=session_id,
                sequence=last.sequence + 1,
                event_type=draft.event_type,
                actor=draft.actor,
                payload=draft.payload,
            )
        )


def workload(fixture: NativeFixture, extension, session_id, root, prepared=None):
    skill, mcp, leases, lease = prepared or catalogs(fixture, extension, session_id, root)
    assert skill is not None and mcp is not None
    events = fixture.events.list_for_session(session_id)
    task = recover_task(
        events,
        workspace=rebuild_workspace(events),
        fallback_title="native",
        attachment_reader=None,
    )
    gateway = build_worker_tool_gateway(
        task,
        settings=replace(_settings(root / "unused.sqlite"), profile="cloud"),
        model_gateway=Mock(),
        session_history=Mock(),
        session_id=session_id,
        runtime=LocalRuntime(),
        runtime_handle=None,
        local_artifacts=None,
        artifact_payload_reader=None,
        cloud_artifacts=None,
        skill_catalog=skill,
        skill_component_names=tuple(s.version.skill_id for s in extension.snapshot.skills),
        cloud_mcp_transport=mcp,
        trusted_local=False,
    )
    policy = LocalPolicyEngine(network_profile=parse_network_profile("mcp-proxy-only"))
    batch = ToolBatchExecutor(
        policy_engine=policy,
        tool_gateway=gateway,
        model_step=HarnessModelStep(),
        verifier=NoopVerifier(),
        parallel_safe_tools=frozenset(),
        parallel_batch_limits=None,
        max_parallel_tool_calls=1,
    )
    completed = []

    def execute(tool, *, approved=False):
        events = fixture.events.list_for_session(session_id)
        context = HarnessContext(
            HarnessTask(title="offline native", user_input="fixed workload"),
            rebuild_session(events),
            HarnessAttempt(1, datetime.now(UTC)),
        )
        message = SessionMessage(
            message_id=new_message_id(),
            role=MessageRole.ASSISTANT,
            content="Offline acceptance proposes the fixed tool call.",
            created_at=datetime.now(UTC),
            tool_calls=(tool,),
        )
        drafts = []
        result = batch.execute(
            context,
            messages=[message],
            completion=ModelCompletion(assistant_message=message, tool_calls=(tool,)),
            tool_calls=(tool,),
            emitted_events=drafts,
            model_calls_used=0,
            tool_calls_executed=0,
            tool_call_limit=4,
            fingerprints=set(),
            metadata={},
            execute_all=True,
            first_execution_started=approved,
        )
        persist(fixture, session_id, drafts)
        completed.extend(d for d in drafts if d.event_type is EventType.TOOL_EXECUTION_COMPLETED)
        return result

    try:
        for tool in (
            call("skills.list", {}),
            call("skills.read", {"name": "native-proof"}),
            call("skills.read", {"name": "native-proof", "file_path": "references/support.txt"}),
        ):
            assert execute(tool).terminal_result is None
        with protocol_stub() as methods:
            tool = call(mcp.model_tools[0].name, {"value": "NATIVE-MCP-PROOF"})
            waiting = execute(tool)
            assert waiting.terminal_result.outcome is HarnessAttemptOutcome.WAITING_APPROVAL
            assert methods == []
            session = rebuild_session(fixture.events.list_for_session(session_id))
            event = ApprovalDecisionService().build_event(
                session=session,
                next_sequence=session.current_sequence + 1,
                command=ApprovalDecisionCommand(
                    ApprovalDecisionAction.GRANT, "native-fixture", "Approve exact offline call"
                ),
            )
            fixture.events.append(event)
            approved = recover_approved_continuation(fixture.events.list_for_session(session_id))
            assert (
                approved is not None
                and approved.tool_call.approval_fingerprint == tool.approval_fingerprint
            )
            # Same continuation start marker used by the Worker, before approved execution.
            fixture.events.append(
                SessionEvent.create(
                    session_id=session_id,
                    sequence=event.sequence + 1,
                    event_type=EventType.TOOL_EXECUTION_STARTED,
                    actor=EventActor.HARNESS,
                    payload={
                        "attempt_number": 1,
                        "tool_name": tool.name,
                        "tool_call_id": str(tool.tool_call_id),
                        "approval_continuation": True,
                    },
                )
            )
            assert execute(approved.tool_call, approved=True).terminal_result is None
            assert methods == ["initialize", "notifications/initialized", "tools/call"]
        assert len(completed) == 4
        assert all(d.payload["status"] == "executed" for d in completed)
        assert "NATIVE-SKILL-PROOF" in completed[2].payload["output"]
        assert "NATIVE-MCP-PROOF" in completed[3].payload["output"]
        return {"tools_executed": 4, "approval_before_wire": True, "mcp_frames": len(methods)}
    finally:
        gateway.close()
        leases.release(session_id, fence=lease.fence)
