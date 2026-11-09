"""Two committed phases: reserve an original, then admit its child once."""

from __future__ import annotations

from collections.abc import Callable, Iterator
from contextlib import contextmanager
from dataclasses import asdict
from typing import Any

from agent_core.domain.identifiers import TaskId
from agent_core.domain.task_bindings import TaskBindingSnapshot
from agent_orchestration.application.orchestration_admission import (
    PreparedOrchestrationChild,
    digest,
    node_budget,
    original_key,
    semantic_digest,
)
from agent_orchestration.application.orchestration_authority import (
    OrchestrationAuthority,
    OrchestrationAuthorizer,
)
from agent_orchestration.application.orchestration_port import (
    OrchestrationToolError,
    TaskRequestReceipt,
)
from agent_orchestration.domain.orchestration import (
    OrchestrationNodeProposal,
    OrchestrationPlanSnapshot,
)
from agent_orchestration.domain.orchestration_budget import BudgetReservation, BudgetUsageReceipt
from psycopg.types.json import Jsonb

from agent_storage.postgres import orchestration_admission_queries as q
from agent_storage.postgres.database import PostgresDatabase
from agent_storage.postgres.subagent_delegation import PostgresSubagentDelegationStore
from agent_storage.postgres.work_unit import borrow_work_unit, postgres_transaction_work_unit

ChildBuilder = Callable[
    [
        OrchestrationAuthority,
        TaskBindingSnapshot,
        OrchestrationPlanSnapshot,
        OrchestrationNodeProposal,
    ],
    PreparedOrchestrationChild,
]
UsageReader = Callable[[Any, TaskId], BudgetUsageReceipt | None]


class PostgresOrchestrationAdmission:
    """Explicit opt-in service; no normal Worker entry is wired in this slice.

    Builder is trusted LOCAL composition, not model input or an external call.
    Authorizer is re-entered on the actual connection in each short phase.
    UsageReader reads durable executor receipts; absence keeps the full reservation.
    """

    def __init__(
        self,
        dsn: str,
        *,
        deployment_namespace: str,
        authorize: OrchestrationAuthorizer,
        build_child: ChildBuilder,
        usage_reader: UsageReader | None = None,
        executor_budget_ready: Callable[[OrchestrationAuthority, OrchestrationNodeProposal], bool]
        | None = None,
    ) -> None:
        self._database = PostgresDatabase(dsn, deployment_namespace=deployment_namespace)
        self._authorize, self._build_child, self._usage_reader = (
            authorize,
            build_child,
            usage_reader,
        )
        self._executor_budget_ready = executor_budget_ready
        self._delegation = PostgresSubagentDelegationStore(
            dsn, deployment_namespace=deployment_namespace
        )

    @property
    def namespace(self) -> str:
        return self._database.deployment_namespace

    def _independent(self) -> None:
        if borrow_work_unit((self._database._dsn, self.namespace)) is not None:
            q.refuse("orchestration_transaction_scope", "admission phases need independent commits")

    @contextmanager
    def _phase(
        self, *, active: bool
    ) -> Iterator[tuple[Any, OrchestrationAuthority, TaskBindingSnapshot]]:
        with self._database.connect() as connection:
            connection.execute("SET LOCAL lock_timeout='500ms'")
            connection.execute("SET LOCAL statement_timeout='3000ms'")
            with postgres_transaction_work_unit(self._database, connection):
                with self._authorize("request") as authority:
                    if not isinstance(authority, OrchestrationAuthority):
                        q.refuse("invalid_authority", "trusted current context is required")
                    if authority.approved_budget is None:
                        q.refuse(
                            "orchestration_budget_authority_required",
                            "current approved budget required",
                        )
                    parent = q.parent_in(connection, self.namespace, authority, active=active)
                    yield connection, authority, parent

    def _require_executor(
        self, authority: OrchestrationAuthority, node: OrchestrationNodeProposal
    ) -> None:
        # Freezing limits is not enforcement. The normal Worker has no cumulative
        # token/runtime consumer yet; 03C must supply this trusted readiness gate.
        if self._executor_budget_ready is None or not self._executor_budget_ready(authority, node):
            q.refuse(
                "orchestration_executor_budget_unavailable", "executor budget guard is not ready"
            )

    def request_task(self, *, run_ref: str, node_key: str) -> TaskRequestReceipt:
        self._independent()
        with self._phase(active=True) as (connection, authority, parent):
            snapshot, node = q.snapshot_in(
                connection, self.namespace, authority, run_ref, node_key, active=False
            )
            key = original_key(self.namespace, snapshot, node_key)
            prior = q.original_in(connection, self.namespace, key)
            if prior is not None:
                q.check_original(prior, self.namespace, snapshot, node_key)
                return q.receipt(prior)  # observation only, never re-enter admission
            q.snapshot_in(connection, self.namespace, authority, run_ref, node_key, active=True)
            self._require_executor(authority, node)
            q.eligible(connection, self.namespace, snapshot, node, authority)
        prepared = self._build_child(authority, parent, snapshot, node)  # no locks held
        prepared.validate(authority, parent, snapshot, node)
        payload = prepared.payload()
        payload_hash = digest(payload)
        try:
            with self._phase(active=True) as (connection, current, current_parent):
                fixed, current_node = q.snapshot_in(
                    connection, self.namespace, current, run_ref, node_key, active=True
                )
                if semantic_digest(self.namespace, fixed, node_key) != semantic_digest(
                    self.namespace, snapshot, node_key
                ):
                    q.refuse("orchestration_original_conflict", "plan moved before reservation")
                prior = q.original_in(connection, self.namespace, key)
                if prior is not None:
                    q.check_original(prior, self.namespace, fixed, node_key)
                    return q.receipt(prior)
                self._require_executor(current, current_node)
                q.eligible(connection, self.namespace, fixed, current_node, current)
                prepared.validate(current, current_parent, fixed, current_node)
                if digest(prepared.payload()) != payload_hash:
                    q.refuse(
                        "orchestration_original_conflict", "child input mutated before reservation"
                    )
                reservation = node_budget(current_node)
                q.budget_in(connection, self.namespace, current, reservation)
                connection.execute(
                    """INSERT INTO orchestration_admission_originals
                       (deployment_namespace,original_key,parent_task_id,run_id,plan_revision,node_key,
                        semantic_digest,payload_digest,payload,child_task_id,reservation,state)
                       VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,'prepared')""",
                    (
                        self.namespace,
                        key,
                        str(current.parent_task_id),
                        run_ref,
                        fixed.plan_revision,
                        node_key,
                        semantic_digest(self.namespace, fixed, node_key),
                        payload_hash,
                        Jsonb(payload),
                        str(prepared.admission.session.session_id),
                        Jsonb(reservation.model_dump(mode="json")),
                    ),
                )
        except OrchestrationToolError:
            raise
        except Exception as error:
            raise OrchestrationToolError("orchestration_admission_unknown", key) from error
        # Only this INSERT winner reaches _execute. Replays, including prepared
        # originals left by a crash here, only observe and retain their reservation.
        try:
            return self._execute(key, prepared)
        except OrchestrationToolError:
            raise
        except Exception as error:
            raise OrchestrationToolError("orchestration_admission_unknown", key) from error

    def _execute(self, key: str, prepared: PreparedOrchestrationChild) -> TaskRequestReceipt:
        with self._phase(active=True) as (connection, authority, parent):
            row = q.original_in(connection, self.namespace, key)
            if row is None or row["state"] != "prepared":
                q.refuse("orchestration_original_conflict", "original is not prepared")
            snapshot, node = q.snapshot_in(
                connection,
                self.namespace,
                authority,
                row["run_id"],
                row["node_key"],
                active=True,
                revision=row["plan_revision"],
            )
            q.check_original(row, self.namespace, snapshot, node.node_key)
            if digest(prepared.payload()) != row["payload_digest"]:
                q.refuse("orchestration_original_conflict", "child input moved after reservation")
            self._require_executor(authority, node)
            reservation = BudgetReservation.model_validate(row["reservation"])
            q.budget_in(connection, self.namespace, authority, reservation, existing=True)
            q.eligible(connection, self.namespace, snapshot, node, authority, owned=reservation)
            prepared.validate(authority, parent, snapshot, node)
            assert prepared.admission.binding is not None  # validated above
            admitted = self._delegation.delegate(prepared.delegation, prepared.admission)
            if (
                str(admitted.child_task_id) != str(row["child_task_id"])
                or admitted.child_binding_digest != prepared.admission.binding.binding_digest
            ):
                q.refuse("orchestration_original_conflict", "delegation returned another child")
            receipt = TaskRequestReceipt(
                run_ref=snapshot.run_ref,
                node_key=node.node_key,
                child_task_id=str(admitted.child_task_id),
            )
            connection.execute(
                "UPDATE subagent_delegation_links SET plan_revision=%s,node_key=%s "
                "WHERE deployment_namespace=%s AND delegation_id=%s",
                (snapshot.plan_revision, node.node_key, self.namespace, admitted.delegation_id),
            )
            connection.execute(
                "UPDATE orchestration_nodes SET child_task_id=%s,status='running',"
                "updated_at=clock_timestamp() WHERE deployment_namespace=%s AND run_id=%s "
                "AND plan_revision=%s AND node_key=%s",
                (
                    admitted.child_task_id,
                    self.namespace,
                    snapshot.run_ref,
                    snapshot.plan_revision,
                    node.node_key,
                ),
            )
            connection.execute(
                "UPDATE orchestration_admission_originals SET state='admitted',receipt=%s "
                "WHERE deployment_namespace=%s AND original_key=%s",
                (Jsonb(asdict(receipt)), self.namespace, key),
            )
            q.parent_in(connection, self.namespace, authority, active=True)
        return receipt  # success only AFTER the child/lineage/node/receipt COMMIT

    def observe(self, key: str) -> dict[str, Any] | None:
        self._independent()
        with self._phase(active=False) as (connection, authority, _parent):
            row = q.original_in(connection, self.namespace, key)
            if row is None:
                return None  # absence is not permission to retry admission
            snapshot, node = q.snapshot_in(
                connection,
                self.namespace,
                authority,
                row["run_id"],
                row["node_key"],
                active=False,
                revision=row["plan_revision"],
            )
            q.check_original(row, self.namespace, snapshot, node.node_key)
            return {
                "original_key": key,
                "state": row["state"],
                "receipt": row["receipt"],
                "reservation": row["reservation"],
                "usage": row["usage"],
            }

    def settle(self, key: str) -> bool:
        """Only authoritative terminal usage can replace a full reservation."""
        self._independent()
        if self._usage_reader is None:
            return False
        with self._phase(active=False) as (connection, authority, _parent):
            row = q.original_in(connection, self.namespace, key)
            if row is None:
                return False
            snapshot, node = q.snapshot_in(
                connection,
                self.namespace,
                authority,
                row["run_id"],
                row["node_key"],
                active=False,
                revision=row["plan_revision"],
            )
            q.check_original(row, self.namespace, snapshot, node.node_key)
            if row["state"] != "admitted":
                return False
            child = q.terminal_child_in(connection, self.namespace, row)
            if child is None:
                return False
            usage = self._usage_reader(connection, row["child_task_id"])
            if usage is None:
                return False
            if (
                not isinstance(usage, BudgetUsageReceipt)
                or usage.child_task_ref != str(row["child_task_id"])
                or not BudgetReservation.model_validate(row["reservation"]).covers(
                    usage.as_reservation()
                )
            ):
                q.refuse("orchestration_usage_conflict", "usage does not fit original reservation")
            if q.terminal_child_in(connection, self.namespace, row) != child:
                q.refuse("orchestration_usage_conflict", "child moved during usage read")
            value = usage.model_dump(mode="json")
            if row["usage"] is not None and row["usage"] != value:
                q.refuse("orchestration_usage_conflict", "original usage receipt is immutable")
            connection.execute(
                "UPDATE orchestration_admission_originals SET usage=%s WHERE "
                "deployment_namespace=%s AND original_key=%s",
                (Jsonb(value), self.namespace, key),
            )
        return True
