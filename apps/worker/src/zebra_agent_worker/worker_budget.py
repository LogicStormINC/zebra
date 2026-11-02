"""Narrow execution gate. Storage commits each reservation before transport."""

from typing import Any

import httpx
from agent_core.ports.worker_budget import (
    ModelBudgetReservation,
    ModelRequestBudget,
    WorkerBudgetBinding,
    WorkerBudgetError,
    WorkerBudgetStore,
)


class TaskBudgetGate:
    def __init__(self, store: WorkerBudgetStore, binding: WorkerBudgetBinding) -> None:
        self.store, self.binding = store, binding

    def start(self) -> None:
        self.store.start(self.binding)

    def check(self) -> float:
        return self.store.check(self.binding)

    def tool_call(self, call_id: str) -> None:
        self.store.reserve_tool(self.binding, call_id)

    @staticmethod
    def ready(model: Any) -> bool:
        client = getattr(model, "_client", False)
        return (
            getattr(model, "worker_budget_hook_contract", None) == "worker-budget/1"
            and callable(getattr(model, "model_request_budget", None))
            and (
                client is None
                or (
                    isinstance(client, httpx.Client)
                    and isinstance(client._transport, httpx.MockTransport)
                )
            )
        )

    def attach_model(self, model: Any) -> Any:
        if not self.ready(model):
            raise WorkerBudgetError("model lacks trusted exact-request counter and transport hook")
        model.worker_budget = self
        return model

    def before_model(self, request: ModelRequestBudget) -> ModelBudgetReservation:
        return self.store.reserve_model(self.binding, request)

    def after_model(self, reservation: ModelBudgetReservation, payload: dict[str, Any]) -> None:
        receipt_id = payload.get("id")
        if not isinstance(receipt_id, str) or not receipt_id or len(receipt_id) > 256:
            raise WorkerBudgetError("provider receipt identity is missing")
        self.store.settle_model(self.binding, reservation, payload.get("usage"), receipt_id)
        self.check()


def prepare_task_budget(
    service: Any, claimed: Any, binding: Any, attempt: int, model: Any, task: Any
) -> TaskBudgetGate | None:
    if service._settings.deployment != "cloud":
        return None
    if binding is None:
        raise WorkerBudgetError("cloud ordinary execution requires a frozen Task binding")
    from agent_storage.postgres.worker_budget import PostgresWorkerBudgetStore

    tokens, seconds, tools = task_budget_limits(binding, task)
    gate = TaskBudgetGate(
        PostgresWorkerBudgetStore(
            service._settings.database_url, deployment_namespace=service._deployment_namespace
        ),
        WorkerBudgetBinding(
            task_id=binding.task_id,
            session_id=claimed.lease.session_id,
            binding_digest=binding.binding_digest,
            fence=claimed.lease.fence,
            attempt_number=attempt,
            max_model_tokens=tokens,
            max_runtime_seconds=seconds,
            max_tool_calls=tools,
        ),
    )
    gate.start()
    # Unsupported providers still get the gate: the real transport refuses before send.
    # Admission separately checks ready(), so this never advertises missing proof as ready.
    if getattr(model, "worker_budget_hook_contract", None) != "worker-budget/1":
        raise WorkerBudgetError("ordinary model transport has no Task budget hook")
    model.worker_budget = gate
    return gate


def task_budget_limits(binding: Any, task: Any) -> tuple[int, int, int]:
    from agent_core.domain.runtime_bundle_types import ConfigurableBudgetDomain

    from zebra_agent_worker.bound_execution_authority import BoundHostExecutionAuthorityResolver
    from zebra_agent_worker.bundle_assembly import task_assembly

    limits = BoundHostExecutionAuthorityResolver(binding=binding).limits
    tokens, seconds, tools = (
        limits.max_model_tokens,
        limits.max_runtime_seconds,
        limits.max_tool_calls,
    )
    assert tokens is not None and seconds is not None and tools is not None
    host = binding.host_capability.host_context
    if host is not None:
        tokens, seconds = (
            min(tokens, host.limits.max_model_tokens),
            min(seconds, host.limits.max_runtime_seconds),
        )
    if task.max_tool_calls is not None:
        tools = min(tools, task.max_tool_calls)
    assembly = task_assembly(task)
    if assembly is not None:
        budget = assembly.bundle.manifest.domains.budget
        if isinstance(budget, ConfigurableBudgetDomain):
            parameters = budget.parameters
            tokens, seconds, tools = (
                min(tokens, parameters.model_tokens),
                min(seconds, parameters.runtime_seconds),
                min(tools, parameters.tool_calls),
            )
    return tokens, seconds, tools


class BudgetExecutionCheck:
    """One callback shared by existing recorder/runtime/network cancellation paths."""

    def __init__(self, original: Any) -> None:
        self.original = original
        self.gate: TaskBudgetGate | None = None

    def __call__(self) -> None:
        self.original()
        if self.gate is not None:
            self.gate.store.check_deadline(self.gate.binding)
