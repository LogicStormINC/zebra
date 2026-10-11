"""Internal child admission must persist, not infer, its canonical Run."""

from dataclasses import replace
from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import Mock
from uuid import UUID, uuid4

import pytest
from agent_core.application.session_bootstrap import (
    SessionBootstrapCommand,
    SessionBootstrapService,
)
from agent_core.application.workspace_projection import rebuild_workspace
from agent_core.contracts.session_commands import validate_accepted_session_command
from agent_core.domain.context_inheritance import ContextInheritanceMode
from agent_core.domain.events import EventType
from agent_core.domain.identifiers import SessionId, TaskId, new_tool_call_id
from agent_core.domain.subagent_delegation import SubagentDelegationReceipt
from agent_core.domain.tool_profiles import ToolProfile
from agent_core.domain.tools import ToolCall, ToolCallStatus
from agent_core.ports.task_admission_transaction import TaskAdmissionRequest
from agent_runtime import LocalToolGateway
from agent_runtime.research_context import delegate_durable_research
from agent_storage import PostgresEventStore, bootstrap_control_plane_epoch
from agent_storage.postgres.subagent_delegation import PostgresSubagentDelegationStore
from agent_storage.postgres.task_admission import PostgresTaskAdmissionTransaction
from zebra_agent_worker.execution_tool_gateway import build_execution_tool_gateway, extensions

from tests.agent_core.test_subagent_delegation_contracts import _parent_binding, _request
from tests.api.test_postgres_host_auth_authorizer import dsn as _native_auth_dsn
from tests.api.test_postgres_host_auth_authorizer import postgres_dsn as _postgres_dsn
from tests.worker.execution.worker_execution_support import _settings
from tests.worker.test_cloud_context_materialization import _task

native_auth_dsn = _native_auth_dsn
postgres_dsn = _postgres_dsn


def _delegation_store():
    store = Mock(spec=PostgresSubagentDelegationStore)
    store.get_link.return_value = None
    admissions = []

    def delegate(request, admission):
        admissions.append((request, admission))
        return SubagentDelegationReceipt(
            delegation_id=request.idempotency_key,
            idempotency_key=request.idempotency_key,
            child_task_id=TaskId(admission.session.session_id),
            child_binding_digest=admission.binding.binding_digest,
        )

    store.delegate.side_effect = delegate
    return store, admissions


def _worker_gateway(tmp_path, parent, store, attempt):
    service = SimpleNamespace(
        _settings=replace(_settings(tmp_path / "unused.sqlite"), profile="cloud"),
        _session_history=Mock(),
        _artifact_payload_store=None,
        _artifact_payload_reader=None,
        _egress_registry=None,
        _delegation_store=store,
        _frozen_manifest_loader=None,
        _client_runtime=None,
        _deployment_namespace="test",
        _extensions=extensions(None, None),
    )
    return build_execution_tool_gateway(
        service,
        task=replace(_task(tmp_path), tool_profile=ToolProfile.GENERAL),
        model_gateway=Mock(),
        session_id=uuid4(),
        runtime=Mock(),
        runtime_handle=Mock(),
        cloud_artifacts=None,
        trusted_local=False,
        task_binding=parent,
        materialized_context=None,
        extension=None,
        fence=Mock(),
        attempt_number=attempt,
    )


def test_child_run_is_persisted_at_admission_and_stable_across_replay(tmp_path):
    parent = _parent_binding()
    store, admissions = _delegation_store()
    call = ToolCall(
        tool_call_id=new_tool_call_id(),
        name="agent.research",
        arguments={"objective": "Collect evidence", "delegation_reason": "Independent read"},
        created_at=datetime.now(UTC),
    )
    for _ in range(2):
        result = delegate_durable_research(
            call,
            objective="Collect evidence",
            delegation_reason="Independent read",
            context_mode=ContextInheritanceMode.FRESH,
            context_source=None,
            workspace_root=tmp_path,
            delegation_store=store,
            parent_task_id=UUID(parent.task_id),
            parent_binding=parent,
            max_model_calls=4,
            max_tool_calls=32,
        )
        assert result.status is ToolCallStatus.EXECUTED

    commands = []
    for request, admission in admissions:
        event = admission.events[-1]
        assert event.event_type is EventType.SESSION_COMMAND_ACCEPTED
        accepted = validate_accepted_session_command(
            event.payload,
            session_id=admission.session.session_id,
            idempotency_key=event.idempotency_key,
        )
        assert accepted.payload["run_id"] == f"subagent-run:{request.idempotency_key}"
        assert accepted.payload["run_id"] != str(admission.session.session_id)
        commands.append(accepted)
    assert len(commands) == 2
    assert commands[0].command_id == commands[1].command_id
    assert commands[0].payload == commands[1].payload


@pytest.mark.parametrize("ingress", ["producer", "local_gateway", "worker_gateway"])
def test_recovered_parent_attempt_and_task_reach_durable_admission(tmp_path, ingress):
    parent = _parent_binding()
    store, admissions = _delegation_store()
    call = ToolCall(
        tool_call_id=new_tool_call_id(),
        name="agent.research",
        arguments={"objective": "Collect evidence", "delegation_reason": "Independent read"},
        created_at=datetime.now(UTC),
    )
    for attempt in (3, 3, 4, 4):
        if ingress == "producer":
            result = delegate_durable_research(
                call,
                objective="Collect evidence",
                delegation_reason="Independent read",
                context_mode=ContextInheritanceMode.FRESH,
                context_source=None,
                workspace_root=tmp_path,
                delegation_store=store,
                parent_task_id=parent.task_id,
                parent_binding=parent,
                parent_attempt_number=attempt,
                max_model_calls=4,
                max_tool_calls=32,
            )
        else:
            if ingress == "local_gateway":
                gateway = LocalToolGateway(
                    tmp_path,
                    model_gateway=Mock(),
                    durable_delegation=True,
                    delegation_store=store,
                    parent_task_id=parent.task_id,
                    parent_binding=parent,
                    parent_attempt_number=attempt,
                )
            else:
                gateway = _worker_gateway(tmp_path, parent, store, attempt)
            try:
                result = gateway.execute(call)
            finally:
                gateway.close()
        assert result.status is ToolCallStatus.EXECUTED
    assert [request.parent_attempt_number for request, _ in admissions] == [3, 3, 4, 4]
    assert all(str(request.parent_task_id) == parent.task_id for request, _ in admissions)
    keys = [
        validate_accepted_session_command(
            admission.events[-1].payload,
            session_id=admission.session.session_id,
            idempotency_key=admission.events[-1].idempotency_key,
        ).payload["run_id"]
        for _, admission in admissions
    ]
    assert keys[0] == keys[1] and keys[2] == keys[3] and keys[0] != keys[2]


@pytest.mark.parametrize("attempt", [0, -1, True, "3", None])
def test_invalid_parent_attempt_is_refused_before_store_access(tmp_path, attempt):
    parent = _parent_binding()
    store, _ = _delegation_store()
    result = delegate_durable_research(
        ToolCall(
            tool_call_id=new_tool_call_id(),
            name="agent.research",
            arguments={},
            created_at=datetime.now(UTC),
        ),
        objective="Collect evidence",
        delegation_reason="Independent read",
        context_mode=ContextInheritanceMode.FRESH,
        context_source=None,
        workspace_root=tmp_path,
        delegation_store=store,
        parent_task_id=parent.task_id,
        parent_binding=parent,
        parent_attempt_number=attempt,
        max_model_calls=4,
        max_tool_calls=32,
    )
    assert result.status is ToolCallStatus.FAILED
    assert result.metadata["reason"] == "durable_delegation_invalid_attempt"
    store.get_link.assert_not_called()
    store.delegate.assert_not_called()


def test_native_child_identity_survives_segment_and_attempt_replay(tmp_path, native_auth_dsn):
    namespace = f"worker-delegation-{uuid4()}"
    bootstrap_control_plane_epoch(native_auth_dsn, deployment_namespace=namespace)
    bootstrap = SessionBootstrapService().build(
        SessionBootstrapCommand(
            title="Parent", user_input="Collect evidence", workspace_root=tmp_path
        )
    )
    parent = _parent_binding().model_copy(update={"task_id": str(bootstrap.session.session_id)})
    PostgresTaskAdmissionTransaction(native_auth_dsn, deployment_namespace=namespace).admit(
        TaskAdmissionRequest(
            events=bootstrap.events,
            session=bootstrap.session,
            workspace=rebuild_workspace(list(bootstrap.events)),
            binding=parent,
        )
    )
    store = PostgresSubagentDelegationStore(native_auth_dsn, deployment_namespace=namespace)
    events = PostgresEventStore(native_auth_dsn, deployment_namespace=namespace)
    call = ToolCall(
        tool_call_id=new_tool_call_id(),
        name="agent.research",
        arguments={"objective": "Collect evidence", "delegation_reason": "Independent read"},
        created_at=datetime.now(UTC),
    )
    children = []
    for attempt in (3, 3, 4, 4):
        gateway = _worker_gateway(tmp_path, parent, store, attempt)
        try:
            result = gateway.execute(call)
        finally:
            gateway.close()
        assert result.status is ToolCallStatus.EXECUTED
        child = TaskId(UUID(result.metadata["child_task_id"]))
        children.append(child)
        link = store.get_link(child)
        assert link is not None and str(link.parent_task_id) == parent.task_id
        commands = [
            event
            for event in events.list_for_session(SessionId(child))
            if event.event_type is EventType.SESSION_COMMAND_ACCEPTED
        ]
        assert len(commands) == 1
        accepted = validate_accepted_session_command(
            commands[0].payload,
            session_id=SessionId(child),
            idempotency_key=commands[0].idempotency_key,
        )
        expected = _request(
            parent,
            parent_task_id=TaskId(UUID(parent.task_id)),
            parent_attempt_number=attempt,
            parent_tool_call_id=str(call.tool_call_id),
        )
        assert accepted.payload["run_id"] == f"subagent-run:{expected.idempotency_key}"
    assert children[0] == children[1] and children[2] == children[3]
    assert children[0] != children[2]


def test_foreign_parent_task_is_refused_before_store_access(tmp_path):
    store, _ = _delegation_store()
    result = delegate_durable_research(
        ToolCall(
            tool_call_id=new_tool_call_id(),
            name="agent.research",
            arguments={},
            created_at=datetime.now(UTC),
        ),
        objective="Collect evidence",
        delegation_reason="Independent read",
        context_mode=ContextInheritanceMode.FRESH,
        context_source=None,
        workspace_root=tmp_path,
        delegation_store=store,
        parent_task_id=uuid4(),
        parent_binding=_parent_binding(),
        max_model_calls=4,
        max_tool_calls=32,
    )
    assert result.status is ToolCallStatus.FAILED
    assert result.metadata["reason"] == "durable_delegation_parent_mismatch"
    store.get_link.assert_not_called()
    store.delegate.assert_not_called()
