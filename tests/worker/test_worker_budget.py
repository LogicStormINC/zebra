"""Worker cumulative gate composition and actual tool boundaries."""

from types import SimpleNamespace
from uuid import uuid4

import httpx
import pytest
from agent_core.ports.worker_budget import WorkerBudgetError
from zebra_agent_worker.worker_budget import BudgetExecutionCheck, TaskBudgetGate
from zebra_agent_worker.worker_tool_gateway import WorkerToolGateway


def test_ready_requires_counter_real_hook_and_cancellable_transport():
    model = SimpleNamespace(model_request_budget=lambda _: None, _client=None)
    assert not TaskBudgetGate.ready(model)
    model.worker_budget_hook_contract = "worker-budget/1"
    assert TaskBudgetGate.ready(model)
    model._client = httpx.Client()
    try:
        assert not TaskBudgetGate.ready(model)
    finally:
        model._client.close()
    model.model_request_budget = None
    assert not TaskBudgetGate.ready(model)


def test_existing_execution_callback_checks_absolute_clock_each_time():
    calls = []
    check = BudgetExecutionCheck(lambda: calls.append("ownership"))
    check()
    check.gate = SimpleNamespace(
        store=SimpleNamespace(check_deadline=lambda binding: calls.append("clock")),
        binding="binding",
    )
    check()
    check()
    assert calls == ["ownership", "ownership", "clock", "ownership", "clock"]


def test_actual_tool_uuid_reserved_before_effect_and_post_deadline_hides_outcome():
    calls = []
    identifier = uuid4()

    def effect(call):
        calls.append("effect")
        return "private-result"

    def expired():
        calls.append("deadline")
        raise WorkerBudgetError("expired")

    gate = SimpleNamespace(tool_call=lambda key: calls.append(key), check=expired)
    gateway = WorkerToolGateway(local=SimpleNamespace(execute=effect), worker_budget=gate)
    with pytest.raises(WorkerBudgetError, match="expired"):
        gateway.execute(SimpleNamespace(tool_call_id=identifier, name="test"))
    assert calls == [str(identifier), "effect", "deadline"]


@pytest.mark.parametrize("root_tokens,root_tools", [(None, None), (100, 0), (14, 0)])
def test_normal_worker_entry_uses_real_task_lease_and_durable_usage(
    tmp_path, monkeypatch, root_tokens, root_tools
):
    """Runtime/context fixture only; real normal entry, PostgreSQL budget and provider wire."""
    import os
    from dataclasses import replace
    from datetime import UTC, datetime, timedelta
    from hashlib import sha256

    from agent_core.domain.modeling import ModelInvocationPolicy
    from agent_core.harness.models import HarnessAttemptOutcome, HarnessAttemptResult
    from agent_core.ports.task_admission_transaction import TaskAdmissionRequest
    from agent_core.ports.worker_budget import ModelRequestBudget
    from agent_integrations.openai_compatible import OpenAICompatibleModelGateway
    from agent_storage import apply_postgres_migrations
    from agent_storage.postgres.database import PostgresDatabase
    from agent_storage.postgres.leases import acquire_lease_in_transaction
    from agent_storage.postgres.task_admission import PostgresTaskAdmissionTransaction
    from agent_storage.postgres.worker_budget import PostgresWorkerBudgetStore
    from zebra_agent_worker.execution import SessionExecutionService

    from tests.agent_storage.test_command_wakeup import _binding
    from tests.worker.test_execution_progress_entry import _entry

    uri = os.environ.get("ZEBRA_TEST_POSTGRES_DSN")
    if not uri:
        pytest.skip("set ZEBRA_TEST_POSTGRES_DSN for owned ordinary Worker acceptance")
    apply_postgres_migrations(uri)
    service, claimed, local, recorder, _, _, _, finished = _entry(
        tmp_path, monkeypatch, admitted=True
    )
    ns = "normal-budget-" + str(uuid4())
    sid = claimed.lease.session_id
    binding = _binding(str(sid))
    database = PostgresDatabase(uri, deployment_namespace=ns)
    from agent_core.application.session_projection import rebuild_session
    from agent_core.application.workspace_projection import rebuild_workspace

    initial = local.events.list_for_session(sid)[:3]
    PostgresTaskAdmissionTransaction(uri, deployment_namespace=ns).admit(
        TaskAdmissionRequest(
            events=tuple(initial),
            session=rebuild_session(initial),
            workspace=rebuild_workspace(initial),
            binding=binding,
        )
    )
    with database.connect() as c:
        c.execute(
            "INSERT INTO control_plane_epochs(deployment_namespace,epoch) VALUES(%s,%s)",
            (ns, claimed.lease.fence.control_plane_epoch),
        )
        lease = acquire_lease_in_transaction(
            c,
            ns,
            sid,
            owner_instance_id=claimed.lease.fence.owner_instance_id,
            ttl=timedelta(seconds=60),
        )
    assert lease.fence == claimed.lease.fence
    claimed = replace(claimed, lease=lease)
    service._settings = replace(service._settings, profile="cloud", database_url=uri)
    service._deployment_namespace = ns
    if root_tokens is not None:
        from agent_core.domain.runtime_bundle_types import (
            BudgetParameters,
            ConfigurableBudgetDomain,
        )
        from zebra_agent_worker.worker_budget import task_budget_limits

        domain = ConfigurableBudgetDomain.model_construct(
            parameters=BudgetParameters.model_construct(
                model_tokens=root_tokens, tool_calls=root_tools, runtime_seconds=60
            )
        )
        assembly = SimpleNamespace(
            bundle=SimpleNamespace(manifest=SimpleNamespace(domains=SimpleNamespace(budget=domain)))
        )

        def configured_limits(frozen, task):
            # Only Assembly lookup is a fixture; execute the real min/zero logic and ledger.
            with monkeypatch.context() as isolated:
                isolated.setattr(
                    "zebra_agent_worker.bundle_assembly.task_assembly", lambda _: assembly
                )
                return task_budget_limits(frozen, task)

        monkeypatch.setattr(
            "zebra_agent_worker.worker_budget.task_budget_limits", configured_limits
        )
    bodies = []

    def reply(wire):
        bodies.append(wire.content)
        with database.connect() as c:
            original = c.execute(
                "SELECT receipt FROM worker_model_reservations "
                "WHERE deployment_namespace=%s AND task_id=%s",
                (ns, sid),
            ).fetchone()
            assert original is not None and original["receipt"] is None
        return httpx.Response(
            200,
            json={
                "id": "normal-1",
                "choices": [
                    {"message": {"role": "assistant", "content": "done"}, "finish_reason": "stop"}
                ],
                "usage": {"prompt_tokens": 2, "completion_tokens": 1, "total_tokens": 3},
            },
        )

    model = OpenAICompatibleModelGateway(
        provider_name="fixture",
        model_name="fixture",
        base_url="https://fixture.invalid",
        api_key="fixture",
        client=httpx.Client(transport=httpx.MockTransport(reply)),
    )
    model.model_request_budget = lambda exact: ModelRequestBudget(
        exact, sha256(exact).hexdigest(), 10, 5, "fixture-known-vocabulary/1"
    )
    monkeypatch.setattr(
        "zebra_agent_worker.execution.execution_gateway.model_gateway",
        lambda *args, **kwargs: model,
    )
    monkeypatch.setattr(
        "zebra_agent_worker.execution.apply_bound_host_context", lambda task, _: task
    )

    def prepared(**kwargs):
        kwargs["task"].max_tool_calls = 2
        return SimpleNamespace(
            claimed=claimed,
            events=kwargs["events"],
            binding=binding,
            materialization=None,
            extension=None,
        )

    monkeypatch.setattr("zebra_agent_worker.execution.prepare_worker_context", prepared)
    monkeypatch.setattr(
        "zebra_agent_worker.execution.execution_runtime.compose_execution_runtime",
        lambda *args, **kwargs: (SimpleNamespace(), None, False),
    )

    def run(*args, **kwargs):
        result = model.complete([], invocation_policy=ModelInvocationPolicy(max_output_tokens=5))
        assert result.assistant_message.content == "done"
        return HarnessAttemptResult(HarnessAttemptOutcome.COMPLETED, "done")

    monkeypatch.setattr("zebra_agent_worker.execution_completion.run_continuation", run)
    result = SessionExecutionService._execute_claimed_session_once(
        service, claimed, started_at=datetime.now(UTC), ownership_check=lambda: None
    )
    assert result == "finished" and finished.call_count == 1
    assert len(bodies) == (0 if root_tokens == 14 else 1)
    gate = model.worker_budget
    if root_tools is not None:
        assert gate.binding.max_tool_calls == root_tools
        with pytest.raises(WorkerBudgetError, match="tool ceiling"):
            gate.tool_call(str(uuid4()))
    restarted = PostgresWorkerBudgetStore(uri, deployment_namespace=ns)
    second = replace(gate.binding, attempt_number=2)
    restarted.start(second)
    with database.connect() as c:
        assert restarted.free_budget(c, sid).model_tokens == (14 if root_tokens == 14 else 97)
        assert not restarted.paid_title_allowed(sid)
    # An expired continuation cannot initiate another wire or publish a successful outcome.
    with database.connect() as c:
        c.execute(
            "UPDATE worker_task_budgets SET deadline=clock_timestamp()-interval '1 second' "
            "WHERE deployment_namespace=%s AND task_id=%s",
            (ns, sid),
        )
    with pytest.raises(WorkerBudgetError):
        model.complete([], invocation_policy=ModelInvocationPolicy(max_output_tokens=5))
    assert len(bodies) == (0 if root_tokens == 14 else 1)
    model._client.close()


@pytest.mark.parametrize("tokens,tools,seconds", [(14, 0, 20), (0, 0, 0), (500, 2, 60)])
def test_configured_root_budget_is_consumed_without_expanding_zero(
    monkeypatch, tokens, tools, seconds
):
    from agent_core.domain.runtime_bundle_types import BudgetParameters, ConfigurableBudgetDomain
    from zebra_agent_worker.worker_budget import task_budget_limits

    from tests.agent_storage.test_command_wakeup import _binding

    parameters = BudgetParameters.model_construct(
        model_tokens=tokens, tool_calls=tools, runtime_seconds=seconds
    )
    domain = ConfigurableBudgetDomain.model_construct(parameters=parameters)
    assembly = SimpleNamespace(
        bundle=SimpleNamespace(manifest=SimpleNamespace(domains=SimpleNamespace(budget=domain)))
    )
    monkeypatch.setattr("zebra_agent_worker.bundle_assembly.task_assembly", lambda _: assembly)
    binding = _binding(str(uuid4()))
    assert task_budget_limits(binding, SimpleNamespace(max_tool_calls=None)) == (
        min(100, tokens),
        min(60, seconds),
        tools,
    )


def test_budgeted_research_refuses_before_legacy_child_creation():
    from datetime import UTC, datetime

    from agent_core.domain.tools import ToolCall, ToolCallStatus

    gateway = WorkerToolGateway(
        local=SimpleNamespace(execute=lambda _: pytest.fail("unreserved child created")),
        worker_budget=SimpleNamespace(
            check=lambda: 10, tool_call=lambda _: pytest.fail("unsupported request charged")
        ),
    )
    result = gateway.execute(
        ToolCall(
            tool_call_id=uuid4(),
            name="agent.research",
            arguments={"objective": "unreserved"},
            created_at=datetime.now(UTC),
        )
    )
    assert result.status is ToolCallStatus.FAILED
    assert result.metadata["reason_code"] == "worker_budget_delegation_unsupported"
