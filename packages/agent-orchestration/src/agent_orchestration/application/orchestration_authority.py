"""Server-owned, current authorization for one orchestration tool call."""

from __future__ import annotations

from contextlib import AbstractContextManager
from dataclasses import dataclass
from typing import Literal, Protocol
from uuid import UUID

from agent_core.domain.identifiers import TaskId

from agent_orchestration.application.orchestration_validation import PlanValidationContext
from agent_orchestration.domain.orchestration_budget import BudgetReservation

OrchestrationAction = Literal["propose", "request"]


@dataclass(frozen=True)
class OrchestrationAuthority:
    """Validated facts supplied by the trusted adapter, never tool arguments.

    Shape checks do not authorize a caller. remaining_budget in validation
    must come from current accounting, not merely the frozen Bundle ceiling.
    """

    parent_task_id: TaskId
    parent_binding_digest: str
    deployment_namespace: str
    validation: PlanValidationContext
    approved_budget: BudgetReservation | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.parent_task_id, UUID) or not self.parent_task_id.int:
            raise ValueError("parent_task_id must be a nonzero UUID")
        digest = self.parent_binding_digest
        if (
            not isinstance(digest, str)
            or len(digest) != 64
            or any(char not in "0123456789abcdef" for char in digest)
        ):
            raise ValueError("parent_binding_digest must be a SHA-256 digest")
        if not isinstance(self.deployment_namespace, str) or not self.deployment_namespace.strip():
            raise ValueError("deployment_namespace must be nonempty")
        if not isinstance(self.validation, PlanValidationContext):
            raise ValueError("validation must be a trusted PlanValidationContext")
        if self.approved_budget is not None and (
            not isinstance(self.approved_budget, BudgetReservation)
            or not self.approved_budget.covers(self.validation.parent_remaining_budget)
        ):
            raise ValueError("approved budget must cover the current free budget")


class OrchestrationAuthorizer(Protocol):
    """Recheck current caller/task authority on EVERY call, deny on failure.

    The adapter must bind its caller/parent and transaction to the store used
    by the runtime. The scope covers current authorization AND all enclosed
    store reads/writes in that same transaction. It must never suppress an
    exception, cache stale grants or substitute a process-local lock. No
    production adapter is supplied here; admission stays closed until 03B/C.
    """

    def __call__(
        self, action: OrchestrationAction
    ) -> AbstractContextManager[OrchestrationAuthority]: ...
