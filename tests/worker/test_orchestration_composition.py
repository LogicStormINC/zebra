"""Trusted request counters are installed on the actual ordinary model instance."""

from types import SimpleNamespace

import pytest
from zebra_agent_worker import execution_tool_gateway as wiring
from zebra_agent_worker.worker_budget import BudgetExecutionCheck, TaskBudgetGate

from tests.worker.test_orchestration_factory import native as published_fixture


def test_server_counter_factory_receives_actual_gateway_and_assembly(monkeypatch):
    model = SimpleNamespace()

    def counter(exact):
        return exact

    seen = []
    settings = object()
    monkeypatch.setattr(wiring, "model_provider_settings", lambda _: settings)

    def resolver(gateway, assembly):
        seen.append((gateway, assembly))
        return counter

    service = SimpleNamespace(
        _settings=object(), _model_http_client=None, _model_request_budget_factory=resolver
    )
    actual = wiring.model_gateway(service, lambda provider: model)
    assert actual is model
    assert seen == [(model, None)]
    assert actual.model_request_budget is counter


def test_missing_server_counter_factory_does_not_invent_capability(monkeypatch):
    monkeypatch.setattr(wiring, "model_provider_settings", lambda _: object())
    model = SimpleNamespace(worker_budget_hook_contract="worker-budget/1")
    service = SimpleNamespace(_settings=object(), _model_http_client=None)
    assert wiring.model_gateway(service, lambda provider: model) is model
    assert not TaskBudgetGate.ready(model)


def test_recorder_ownership_callback_uses_ambient_safe_clock_only():
    calls = []
    store = SimpleNamespace(check_deadline=lambda binding: calls.append(binding))
    binding = object()
    check = BudgetExecutionCheck(lambda: calls.append("ownership"))
    check.gate = TaskBudgetGate(store, binding)
    check()
    assert calls == ["ownership", binding]


@pytest.fixture
def native(request):
    return published_fixture.__wrapped__(request)


def test_real_gateway_tools_use_native_registry_binding_and_child_snapshot(
    native, tmp_path, monkeypatch
):
    import json
    from dataclasses import replace
    from datetime import UTC, datetime
    from unittest.mock import Mock
    from uuid import UUID, uuid4

    from agent_core.domain.events import EventType
    from agent_core.domain.tools import ToolCall, ToolCallStatus
    from agent_runtime import LocalRuntime
    from zebra_agent_worker.execution_tool_gateway import ExtensionRuntime

    from tests.worker.test_loop import _settings
    from tests.worker.test_orchestration_factory import TrustedFixtureGateway, _proposal

    factory, task, parent, model, fence, role, _ = native
    monkeypatch.setenv(role.bound_version.runtime_assembly.provider_profile.api_key_env, "fixture")
    inspected = []

    def counters(actual, assembly):
        if (
            assembly is None
            or actual._assembly != assembly
            or actual._model_name != assembly.bundle.manifest.domains.model.parameters.model
        ):
            return None
        inspected.append(assembly.assembly_digest)
        return TrustedFixtureGateway._counter

    factory.model_request_budget_factory = counters
    service = SimpleNamespace(
        _settings=replace(_settings(tmp_path / "unused.sqlite"), profile="cloud"),
        _extensions=ExtensionRuntime(None, None),
        _orchestration_factory=factory,
        _session_history=Mock(),
        _artifact_payload_store=None,
        _artifact_payload_reader=None,
        _egress_registry=None,
        _delegation_store=None,
        _deployment_namespace=factory.namespace,
        _frozen_manifest_loader=None,
        _client_runtime=None,
    )
    gateway = wiring.build_execution_tool_gateway(
        service,
        task=task,
        model_gateway=model,
        session_id=UUID(parent.task_id),
        runtime=LocalRuntime(),
        runtime_handle=None,
        cloud_artifacts=None,
        trusted_local=False,
        task_binding=parent,
        materialized_context=None,
        extension=None,
        fence=fence,
    )
    gateway.worker_budget = model.worker_budget

    def call(name, arguments):
        return gateway.execute(
            ToolCall(
                tool_call_id=uuid4(), name=name, arguments=arguments, created_at=datetime.now(UTC)
            )
        )

    try:
        proposed = call("orchestration.plan.propose", _proposal().model_dump(mode="json"))
        assert proposed.status is ToolCallStatus.EXECUTED, proposed.output
        run_ref = json.loads(proposed.output)["runRef"]
        assert factory.store.read_run_status(run_ref) == "running"
        requested = call("orchestration.task.request", {"run_ref": run_ref, "node_key": "inspect"})
        assert requested.status is ToolCallStatus.EXECUTED, requested.output
        child_id = json.loads(requested.output)["childTaskId"]
        with factory.database.connect() as connection:
            snapshot = connection.execute(
                "SELECT snapshot_json FROM task_binding_snapshots "
                "WHERE deployment_namespace=%s AND task_id=%s",
                (factory.namespace, child_id),
            ).fetchone()["snapshot_json"]
            prepared = connection.execute(
                "SELECT payload FROM session_events WHERE deployment_namespace=%s "
                "AND session_id=%s AND event_type=%s",
                (factory.namespace, child_id, EventType.TASK_PREPARED.value),
            ).fetchone()["payload"]["definition_snapshot"]
        assert prepared["definition_id"] == str(role.definition_id)
        assert prepared["bound_version"][
            "runtime_assembly"
        ] == role.bound_version.runtime_assembly.model_dump(mode="json")
        assert (
            snapshot["agent_capability_ceiling"]["definition_snapshot_digest"]
            == prepared["snapshot_digest"]
        )
        assert inspected == [role.bound_version.runtime_assembly.assembly_digest] * 3
    finally:
        gateway.close()

    ordinary = wiring.build_execution_tool_gateway(
        service,
        task=replace(task, definition_snapshot=role),
        model_gateway=model,
        session_id=UUID(parent.task_id),
        runtime=LocalRuntime(),
        runtime_handle=None,
        cloud_artifacts=None,
        trusted_local=False,
        task_binding=parent,
        materialized_context=None,
        extension=None,
        fence=fence,
    )
    try:
        assert not any(tool.name.startswith("orchestration.") for tool in ordinary.model_tools)
    finally:
        ordinary.close()


def test_late_usage_scan_follows_active_segment_but_keeps_original_child(native, monkeypatch):
    from uuid import UUID, uuid4

    from agent_core.domain.sessions import SessionStatus
    from agent_storage.postgres.projections import PostgresProjectionStore
    from zebra_agent_worker.orchestration_wakeup_hook import OrchestrationWakeupHook

    from tests.worker.test_orchestration_factory import TrustedFixtureGateway, _proposal, _runtime

    factory, _, parent, _, _, role, _ = native
    monkeypatch.setenv(role.bound_version.runtime_assembly.provider_profile.api_key_env, "fixture")
    factory.model_request_budget_factory = lambda model, assembly: TrustedFixtureGateway._counter
    runtime = _runtime(native)
    proposal = runtime.propose_plan(_proposal())
    child = runtime.request_task(run_ref=proposal.run_ref, node_key="inspect")
    projections = PostgresProjectionStore(
        factory.database._dsn, deployment_namespace=factory.namespace
    )
    root_segment = projections.get_session(UUID(child.child_task_id))
    next_segment_id = uuid4()
    with factory.database.connect() as connection:
        # This regression supplies the persisted rollover facts directly: the
        # discovery query must use the Task pointer, not the old root projection.
        connection.execute(
            "INSERT INTO session_projections "
            "(deployment_namespace,session_id,title,status,created_at,updated_at,current_sequence) "
            "SELECT deployment_namespace,%s,title,'completed',created_at,updated_at, "
            "current_sequence "
            "FROM session_projections WHERE deployment_namespace=%s AND session_id=%s",
            (next_segment_id, factory.namespace, child.child_task_id),
        )
        connection.execute(
            "INSERT INTO execution_segments "
            "(deployment_namespace,session_id,task_id,predecessor_id,segment_index,visibility, "
            "rollover_reason) "
            "VALUES(%s,%s,%s,%s,1,'internal','context_pressure')",
            (factory.namespace, next_segment_id, child.child_task_id, child.child_task_id),
        )
        connection.execute(
            "UPDATE agent_tasks SET active_segment_id=%s "
            "WHERE deployment_namespace=%s AND task_id=%s",
            (next_segment_id, factory.namespace, child.child_task_id),
        )
        original = connection.execute(
            "SELECT original_key,run_id,plan_revision,node_key,child_task_id "
            "FROM orchestration_admission_originals WHERE deployment_namespace=%s",
            (factory.namespace,),
        ).fetchone()
    assert root_segment.status is not SessionStatus.COMPLETED
    attempts = []
    hook = OrchestrationWakeupHook(
        factory.database._dsn,
        deployment_namespace=factory.namespace,
        settle_original=lambda key, task: attempts.append((key, task)) or False,
    )
    hook.reconcile_pending()
    assert factory.store.read_node_statuses(proposal.run_ref)["inspect"] == "completed"
    # A missing usage receipt remains eligible after the bounded cursor wraps.
    hook.reconcile_pending()
    hook.reconcile_pending()
    assert attempts == [(original["original_key"], parent.task_id)] * 2
    with factory.database.connect() as connection:
        after = connection.execute(
            "SELECT original_key,run_id,plan_revision,node_key,child_task_id "
            "FROM orchestration_admission_originals WHERE deployment_namespace=%s",
            (factory.namespace,),
        ).fetchone()
    assert after == original
