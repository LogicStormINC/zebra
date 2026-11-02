"""Native Worker composition for current, published orchestration identities."""

from __future__ import annotations

from collections.abc import Callable, Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any, cast
from uuid import UUID

from agent_core.application.session_bootstrap import (
    SessionBootstrapCommand,
    SessionBootstrapService,
)
from agent_core.application.workspace_projection import rebuild_workspace
from agent_core.contracts.session_commands import SessionCommand, SessionCommandKind
from agent_core.domain.bundle_definition import BundleDefinitionSnapshot, parse_definition_snapshot
from agent_core.domain.events import EventActor, EventType, SessionEvent
from agent_core.domain.execution_authority import (
    ExecutionAuthorityDecision,
    ExecutionAuthorityRevalidation,
    ExecutionAuthoritySnapshot,
)
from agent_core.domain.identifiers import TaskId
from agent_core.domain.leases import LeaseFence
from agent_core.domain.subagent_delegation import SubagentDelegationRequest
from agent_core.domain.task_bindings import TaskBindingSnapshot, host_context_digest
from agent_core.ports.model_gateway import ModelGatewayPort
from agent_core.ports.task_admission_transaction import TaskAdmissionRequest
from agent_integrations.bundle_model import BundleModelGateway
from agent_orchestration.application.orchestration_admission import (
    PreparedOrchestrationChild,
    derive_orchestration_child_binding,
    original_key,
)
from agent_orchestration.application.orchestration_authority import OrchestrationAuthority
from agent_orchestration.application.orchestration_runtime import (
    OrchestrationRuntime,
    OrchestrationStorePort,
)
from agent_orchestration.application.orchestration_validation import PlanValidationContext
from agent_orchestration.domain.orchestration_budget import BudgetReservation
from agent_storage.postgres import orchestration_admission_queries as q
from agent_storage.postgres.agent_registry import PostgresAgentRegistry
from agent_storage.postgres.database import PostgresDatabase
from agent_storage.postgres.orchestration import PostgresOrchestrationStore
from agent_storage.postgres.orchestration_admission import PostgresOrchestrationAdmission
from agent_storage.postgres.work_unit import postgres_work_unit
from agent_storage.postgres.worker_budget import PostgresWorkerBudgetStore

from zebra_agent_worker.orchestration_roles import PublishedOrchestrationRoles, refuse
from zebra_agent_worker.task_recovery import RecoveredTask
from zebra_agent_worker.worker_budget import TaskBudgetGate

if TYPE_CHECKING:
    from zebra_agent_worker.execution_tool_gateway import ModelRequestBudgetFactory


@dataclass(frozen=True)
class _PublishedChild(PreparedOrchestrationChild):
    check_publication: Callable[[], None]

    def validate(self, authority: Any, parent: Any, snapshot: Any, node: Any) -> None:
        super().validate(authority, parent, snapshot, node)
        # B calls validation again inside EACH committed admission phase.
        self.check_publication()


class PostgresOrchestrationFactory:
    def __init__(
        self,
        dsn: str,
        namespace: str,
        *,
        model_request_budget_factory: ModelRequestBudgetFactory | None = None,
    ) -> None:
        self.model_request_budget_factory = model_request_budget_factory
        self.database = PostgresDatabase(dsn, deployment_namespace=namespace)
        self.namespace = namespace
        self.roles = PublishedOrchestrationRoles(
            PostgresAgentRegistry(dsn, deployment_namespace=namespace)
        )
        self.budgets = PostgresWorkerBudgetStore(dsn, deployment_namespace=namespace)
        self.store = PostgresOrchestrationStore(dsn, deployment_namespace=namespace)

    def __call__(
        self,
        *,
        task: RecoveredTask,
        binding: TaskBindingSnapshot | None,
        fence: LeaseFence,
        model_gateway: ModelGatewayPort,
        attempt_number: int,
    ) -> OrchestrationRuntime | None:
        snapshot = task.definition_snapshot
        if not isinstance(snapshot, BundleDefinitionSnapshot):
            return None
        with postgres_work_unit(self.database), self.database.connect() as c:
            definition = self.roles.registry.get_definition(snapshot.scope)
            if definition is None or definition.name != "system/orchestrator":
                return None
            self.roles.current(c, snapshot, frozen=True)
        if (
            binding is None
            or binding.agent_capability_ceiling.definition_snapshot_digest
            != snapshot.snapshot_digest
        ):
            refuse("orchestrator binding must name the real Task Definition snapshot")
        gate = getattr(model_gateway, "worker_budget", None)

        @contextmanager
        def authorize(action: str) -> Iterator[OrchestrationAuthority]:
            if (
                not isinstance(gate, TaskBudgetGate)
                or gate.store is None
                or not TaskBudgetGate.ready(model_gateway)
                or gate.binding.task_id != binding.task_id
                or gate.binding.binding_digest != binding.binding_digest
                or gate.binding.fence != fence
                or gate.binding.attempt_number != attempt_number
            ):
                refuse("trusted cumulative Worker budget and transport are required")
            with postgres_work_unit(self.database), self.database.connect() as c:
                c.execute("SET LOCAL lock_timeout='500ms'")
                c.execute("SET LOCAL statement_timeout='3000ms'")
                approved, free = self.budgets.current_authority(c, gate.binding)
                current = self._current(
                    c, binding, snapshot, action, attempt_number=attempt_number, budget=approved
                )
                context = current.host_capability.host_context
                assert context is not None  # _current refuses missing Host authority
                published = self.roles.roles(c, snapshot)
                yield OrchestrationAuthority(
                    parent_task_id=TaskId(UUID(binding.task_id)),
                    parent_binding_digest=current.binding_digest,
                    deployment_namespace=self.namespace,
                    approved_budget=approved,
                    validation=PlanValidationContext(
                        parent_capabilities=current.effective_capabilities,
                        parent_resource_refs=frozenset(context.resource_refs),
                        parent_remaining_budget=free,
                        published_roles=frozenset(published),
                    ),
                )

        admission = PostgresOrchestrationAdmission(
            self.database._dsn,
            deployment_namespace=self.namespace,
            authorize=authorize,
            build_child=self._builder(task, snapshot),
            usage_reader=self.budgets.usage_reader,
            executor_budget_ready=lambda authority, node: self._executor_ready(snapshot, node),
        )
        return OrchestrationRuntime(
            cast(OrchestrationStorePort, self.store),
            authorize=authorize,
            admission=admission,
            require_persisted_gate=True,
            auto_materialize=True,
        )

    def _current(
        self,
        c: Any,
        binding: TaskBindingSnapshot,
        snapshot: BundleDefinitionSnapshot,
        action: str,
        *,
        attempt_number: int | None = None,
        active: bool = True,
        budget: BudgetReservation | None = None,
    ) -> TaskBindingSnapshot:
        name, _ = self.roles.current(c, snapshot, frozen=True)
        if name != "system/orchestrator":
            refuse("current Definition is not the system orchestrator")
        # q.parent_in checks the latest binding and STOP in the same locked transaction.
        provisional = OrchestrationAuthority(
            parent_task_id=TaskId(UUID(binding.task_id)),
            parent_binding_digest=binding.binding_digest,
            deployment_namespace=self.namespace,
            validation=PlanValidationContext(parent_capabilities=binding.effective_capabilities),
        )
        current = q.parent_in(c, self.namespace, provisional, active=active)
        needed = (
            "orchestration.plan.propose" if action == "propose" else "orchestration.task.request"
        )
        host = current.host_capability
        context = host.host_context
        now = datetime.now(UTC)
        if (
            needed not in current.effective_capabilities
            or context is None
            or host.grant_expires_at is None
            or host.grant_expires_at <= now
            or context.expires_at is None
            or context.expires_at <= now
            or host_context_digest(context) != host.grant_digest
            or current.agent_capability_ceiling.definition_snapshot_digest
            != snapshot.snapshot_digest
        ):
            refuse("current capability, grant expiry or Definition binding refuses orchestration")
        row = c.execute(
            "SELECT e.event_type,e.payload FROM session_events e JOIN agent_tasks t "
            "ON t.deployment_namespace=e.deployment_namespace AND t.task_id=e.task_id "
            "AND t.active_segment_id=e.session_id WHERE e.deployment_namespace=%s "
            "AND e.task_id=%s AND e.event_type IN (%s,%s) "
            "ORDER BY e.task_sequence DESC LIMIT 1",
            (
                self.namespace,
                binding.task_id,
                EventType.EXECUTION_AUTHORITY_RESOLVED.value,
                EventType.EXECUTION_AUTHORITY_REVALIDATED.value,
            ),
        ).fetchone()
        if row is None:
            refuse("current durable execution authority is unavailable")
        proof: ExecutionAuthoritySnapshot | None
        if row["event_type"] == EventType.EXECUTION_AUTHORITY_RESOLVED.value:
            proof = ExecutionAuthoritySnapshot.model_validate(row["payload"])
        else:
            revalidated = ExecutionAuthorityRevalidation.model_validate(row["payload"])
            if revalidated.decision not in {
                ExecutionAuthorityDecision.ALLOWED,
                ExecutionAuthorityDecision.NARROWED,
            }:
                refuse("current execution authority denies orchestration")
            proof = revalidated.effective_snapshot
        if (
            proof is None
            or proof.resolution
            not in {ExecutionAuthorityDecision.ALLOWED, ExecutionAuthorityDecision.NARROWED}
            or proof.expires_at <= now
            or proof.validated_at > now
            or (attempt_number is not None and proof.attempt_number != attempt_number)
            or proof.agent_definition_snapshot_digest != snapshot.snapshot_digest
            or proof.authority_issuer != host.authority_issuer
            or proof.source_authority_digest != binding.binding_digest
            or proof.policy_effective_digest != binding.zebra_policy_digest
            or proof.namespace_id != host.namespace_id
            or "agent.execute" not in proof.granted_authorities
        ):
            refuse("durable execution authority is stale or belongs to another Task")
        if budget is not None:
            for amount, ceiling in (
                (budget.model_tokens, proof.effective_limits.max_model_tokens),
                (budget.tool_calls, proof.effective_limits.max_tool_calls),
                (budget.runtime_seconds, proof.effective_limits.max_runtime_seconds),
            ):
                if ceiling is not None and amount > ceiling:
                    refuse("current execution authority narrowed the approved budget")
        return current

    def settle_original(self, key: str, parent_task_id: Any) -> bool:
        """Observe and settle one durable original; never dispatch or need a live lease."""
        with postgres_work_unit(self.database), self.database.connect() as c:
            row = c.execute(
                "SELECT b.snapshot_json,e.payload FROM agent_tasks t "
                "JOIN LATERAL (SELECT snapshot_json FROM task_binding_snapshots "
                "WHERE deployment_namespace=t.deployment_namespace AND task_id=t.task_id "
                "ORDER BY binding_revision DESC LIMIT 1) b ON true "
                "JOIN LATERAL (SELECT payload FROM session_events "
                "WHERE deployment_namespace=t.deployment_namespace AND task_id=t.task_id "
                "AND event_type=%s ORDER BY task_sequence LIMIT 1) e ON true "
                "WHERE t.deployment_namespace=%s AND t.task_id=%s",
                (EventType.TASK_PREPARED.value, self.namespace, str(parent_task_id)),
            ).fetchone()
            if row is None:
                return False
            binding = TaskBindingSnapshot.model_validate(row["snapshot_json"])
            snapshot = parse_definition_snapshot(row["payload"].get("definition_snapshot"))
            if not isinstance(snapshot, BundleDefinitionSnapshot):
                return False

        @contextmanager
        def authorize(action: str) -> Iterator[OrchestrationAuthority]:
            with postgres_work_unit(self.database), self.database.connect() as c:
                c.execute("SET LOCAL lock_timeout='500ms'")
                c.execute("SET LOCAL statement_timeout='3000ms'")
                current = self._current(c, binding, snapshot, action, active=False)
                budgets = self.budgets.inactive_authority(
                    c, binding.task_id, binding.binding_digest
                )
                if budgets is None:
                    refuse("current parent budget is unavailable")
                approved, free = budgets
                yield OrchestrationAuthority(
                    parent_task_id=TaskId(UUID(binding.task_id)),
                    parent_binding_digest=current.binding_digest,
                    deployment_namespace=self.namespace,
                    approved_budget=approved,
                    validation=PlanValidationContext(
                        parent_capabilities=current.effective_capabilities,
                        parent_remaining_budget=free,
                    ),
                )

        admission = PostgresOrchestrationAdmission(
            self.database._dsn,
            deployment_namespace=self.namespace,
            authorize=authorize,
            build_child=lambda *args: refuse("settlement cannot create a child"),
            usage_reader=self.budgets.usage_reader,
        )
        return admission.settle(key)

    def _executor_ready(self, parent_snapshot: BundleDefinitionSnapshot, node: Any) -> bool:
        # The same trusted resolver configures ordinary Worker transport; parent
        # readiness never proves this independently published child's provider.
        if self.model_request_budget_factory is None:
            return False
        with postgres_work_unit(self.database), self.database.connect() as c:
            roles = self.roles.roles(c, parent_snapshot)
            role = roles.get(node.preferred_agent_role)
            if role is None:
                return False
            assembly = role.bound_version.runtime_assembly
            try:
                model = BundleModelGateway(assembly)
                counter = self.model_request_budget_factory(model, assembly)
            except (ValueError, TypeError):
                return False
            if counter is None:
                return False
            model.model_request_budget = counter
            return TaskBudgetGate.ready(model)

    def _builder(self, task: RecoveredTask, parent_snapshot: BundleDefinitionSnapshot) -> Any:
        def build(
            authority: Any, parent: Any, snapshot: Any, node: Any
        ) -> PreparedOrchestrationChild:
            with postgres_work_unit(self.database), self.database.connect() as c:
                self.roles.current(c, parent_snapshot, frozen=True)
                roles = self.roles.roles(c, parent_snapshot)
                role = roles.get(node.preferred_agent_role)
                if role is None:
                    refuse("requested role has no unambiguous current published Definition")
            key = original_key(self.namespace, snapshot, node.node_key)
            delegation = SubagentDelegationRequest(
                parent_task_id=authority.parent_task_id,
                parent_attempt_number=1,
                parent_tool_call_id=key,
                delegation_index=0,
                role=node.preferred_agent_role,
                objective=node.objective,
                requested_capabilities=node.required_capabilities,
                resource_refs=node.resource_refs,
                isolation_mode=node.isolation_mode,
                child_definition_snapshot_digest=role.snapshot_digest,
                child_capability_profile_ref=role.tool_profile_ref,
                expected_parent_binding_digest=authority.parent_binding_digest,
            )
            provisional = derive_orchestration_child_binding(
                parent,
                delegation,
                UUID(int=1),
                node,
                parent_resource_refs=authority.validation.parent_resource_refs,
            )
            boot = SessionBootstrapService().build(
                SessionBootstrapCommand(
                    title=f"{node.preferred_agent_role}: {node.node_key}",
                    user_input=node.objective,
                    workspace_root=Path(task.workspace_root),
                    policy_profile=task.policy_profile,
                    tool_profile=task.tool_profile,
                    network_profile=task.network_profile.name.value,
                    network_allowlist=task.network_profile.domain_allowlist,
                    mcp_allowlist=task.mcp_allowlist or (),
                    skill_components=task.skill_components or (),
                    max_attempts=1,
                    max_model_calls=node.max_model_calls,
                    max_tool_calls=node.max_tool_calls,
                    host_context=provisional.host_capability.host_context,
                    definition_snapshot=role,
                )
            )
            child = derive_orchestration_child_binding(
                parent,
                delegation,
                boot.session.session_id,
                node,
                parent_resource_refs=authority.validation.parent_resource_refs,
            )
            command = SessionCommand(
                session_id=boot.session.session_id,
                kind=SessionCommandKind.RUN,
                expected_revision=boot.events[-1].sequence,
                idempotency_key=key,
            )
            event = SessionEvent.create(
                session_id=boot.session.session_id,
                sequence=len(boot.events),
                event_type=EventType.SESSION_COMMAND_ACCEPTED,
                actor=EventActor.HARNESS,
                payload=command.event_payload(),
                idempotency_key=key,
            )

            def check_publication() -> None:
                with postgres_work_unit(self.database), self.database.connect() as c:
                    self.roles.current(c, role)

            return _PublishedChild(
                delegation,
                TaskAdmissionRequest(
                    events=(*boot.events, event),
                    session=boot.session,
                    workspace=rebuild_workspace(list(boot.events)),
                    binding=child,
                ),
                check_publication,
            )

        return build
