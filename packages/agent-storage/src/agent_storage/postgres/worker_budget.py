"""Ordinary Worker Task ledger: independent pre-send commits, unknown never refunds."""

from collections.abc import Iterator
from contextlib import contextmanager
from math import ceil
from typing import Any
from uuid import UUID, uuid4

from agent_core.domain.leases import LeaseFence
from agent_core.ports.worker_budget import (
    ModelBudgetReservation,
    ModelRequestBudget,
    WorkerBudgetBinding,
    WorkerBudgetError,
    trusted_usage,
)
from agent_orchestration.domain.orchestration_budget import BudgetReservation, BudgetUsageReceipt
from psycopg.errors import LockNotAvailable
from psycopg.types.json import Jsonb

from agent_storage.postgres import worker_budget_queries as q
from agent_storage.postgres.database import PostgresDatabase
from agent_storage.postgres.work_unit import borrow_work_unit, postgres_transaction_work_unit


class PostgresWorkerBudgetStore:
    def __init__(self, dsn: str, *, deployment_namespace: str) -> None:
        self._database = PostgresDatabase(dsn, deployment_namespace=deployment_namespace)
        self.namespace = deployment_namespace

    @contextmanager
    def _phase(self) -> Iterator[Any]:
        if borrow_work_unit((self._database._dsn, self.namespace)) is not None:
            raise WorkerBudgetError("Worker budget requires independent committed phases")
        with self._database.connect() as connection:
            connection.execute(
                """SELECT set_config('lock_timeout','500ms',true),
                          set_config('statement_timeout','3000ms',true)"""
            )
            with postgres_transaction_work_unit(self._database, connection):
                yield connection

    def start(self, binding: WorkerBudgetBinding) -> None:
        with self._phase() as c:
            now = q.boundary(c, self.namespace, binding)
            c.execute(
                """INSERT INTO worker_task_budgets
                (deployment_namespace,task_id,binding_digest,started_at,deadline,
                 max_model_tokens,max_tool_calls,last_session_id,last_fence,last_attempt)
                VALUES(%s,%s,%s,%s,%s + make_interval(secs => %s),%s,%s,%s,%s,%s)
                ON CONFLICT(deployment_namespace,task_id) DO NOTHING""",
                (
                    self.namespace,
                    binding.task_id,
                    binding.binding_digest,
                    now,
                    now,
                    binding.max_runtime_seconds,
                    binding.max_model_tokens,
                    binding.max_tool_calls,
                    binding.session_id,
                    Jsonb(binding.fence.model_dump(mode="json")),
                    binding.attempt_number,
                ),
            )
            q.remaining(c, self.namespace, binding, require_segment=False)
            inherited = q.ancestor_deadline(c, self.namespace, binding.task_id)
            if inherited is not None:
                c.execute(
                    "UPDATE worker_task_budgets SET deadline=least(deadline,%s) "
                    "WHERE deployment_namespace=%s AND task_id=%s",
                    (inherited, self.namespace, binding.task_id),
                )
            # Narrowing cannot reset a Task clock or erase its prior charged effects.
            c.execute(
                """UPDATE worker_task_budgets SET
                deadline=least(deadline,started_at+make_interval(secs => %s)),
                max_model_tokens=least(max_model_tokens,%s),max_tool_calls=least(max_tool_calls,%s),
                last_session_id=%s,last_fence=%s,last_attempt=%s
                WHERE deployment_namespace=%s AND task_id=%s""",
                (
                    binding.max_runtime_seconds,
                    binding.max_model_tokens,
                    binding.max_tool_calls,
                    binding.session_id,
                    Jsonb(binding.fence.model_dump(mode="json")),
                    binding.attempt_number,
                    self.namespace,
                    binding.task_id,
                ),
            )
            q.remaining(c, self.namespace, binding)

    def check_deadline(self, binding: WorkerBudgetBinding) -> None:
        # Existing ownership callback checks STOP/lease. This non-mutating clock poll
        # also runs inside recorder transactions and after terminal writes for cleanup.
        with self._database.connect() as c:
            row = c.execute(
                "WITH lineage AS (" + q.ANCESTOR_DEADLINE_SQL + """)
                   SELECT lineage.*, active.bound, clock_timestamp() AS now
                   FROM lineage LEFT JOIN (
                   SELECT true AS bound FROM worker_task_budgets b
                   JOIN agent_tasks t ON t.deployment_namespace=b.deployment_namespace
                     AND t.task_id=b.task_id
                   WHERE b.deployment_namespace=%s AND b.task_id=%s AND b.binding_digest=%s
                     AND t.active_segment_id=%s AND b.last_session_id=%s AND b.last_fence=%s
                     AND b.last_attempt=%s
                     AND b.binding_digest=(SELECT binding_digest FROM task_binding_snapshots
                       WHERE deployment_namespace=b.deployment_namespace AND task_id=b.task_id
                       ORDER BY binding_revision DESC LIMIT 1)
                   ) active ON true""",
                (
                    binding.task_id,
                    self.namespace,
                    self.namespace,
                    self.namespace,
                    binding.task_id,
                    binding.binding_digest,
                    binding.session_id,
                    binding.session_id,
                    Jsonb(binding.fence.model_dump(mode="json")),
                    binding.attempt_number,
                ),
            ).fetchone()
            if row is None:
                raise WorkerBudgetError("Task deadline exceeded or binding moved")
            deadline = q.validated_ancestor_deadline(row)
            if not row["bound"] or deadline is None or deadline <= row["now"]:
                raise WorkerBudgetError("Task deadline exceeded or binding moved")

    def check(self, binding: WorkerBudgetBinding) -> float:
        # This read can be retried after rollback without repeating a provider call.
        for attempt in range(2):
            try:
                with self._phase() as c:
                    return q.remaining(c, self.namespace, binding)
            except LockNotAvailable:
                if attempt == 1:
                    raise
        raise AssertionError("unreachable budget check retry state")

    def reserve_model(
        self, binding: WorkerBudgetBinding, request: ModelRequestBudget
    ) -> ModelBudgetReservation:
        reservation = ModelBudgetReservation(
            str(uuid4()), request.request_digest, request.input_upper_bound, request.output_cap
        )
        with self._phase() as c:
            q.remaining(c, self.namespace, binding)
            unknown = c.execute(
                """SELECT 1 FROM worker_model_reservations WHERE deployment_namespace=%s
                   AND task_id=%s AND request_digest=%s AND receipt IS NULL LIMIT 1""",
                (self.namespace, binding.task_id, request.request_digest),
            ).fetchone()
            if unknown is not None:
                raise WorkerBudgetError("exact request has unknown original; observe, never resend")
            child_tokens, _, _ = q.child_charges(c, self.namespace, binding.task_id)
            changed = c.execute(
                """WITH charged AS (
                       UPDATE worker_task_budgets SET charged_tokens=charged_tokens+%s
                       WHERE deployment_namespace=%s AND task_id=%s
                       AND charged_tokens+%s+%s<=max_model_tokens
                       RETURNING deployment_namespace,task_id
                   )
                   INSERT INTO worker_model_reservations
                   SELECT deployment_namespace,task_id,%s,%s,%s,%s,%s,%s,%s,%s,NULL
                   FROM charged RETURNING reservation_id""",
                (
                    reservation.token_bound,
                    self.namespace,
                    binding.task_id,
                    reservation.token_bound,
                    child_tokens,
                    reservation.reservation_id,
                    request.request_digest,
                    binding.session_id,
                    binding.attempt_number,
                    Jsonb(binding.fence.model_dump(mode="json")),
                    request.input_upper_bound,
                    request.output_cap,
                    request.counter_contract,
                ),
            ).fetchone()
            if changed is None:
                raise WorkerBudgetError("Task cumulative model token ceiling exceeded")
            q.remaining(c, self.namespace, binding)
        return reservation

    def settle_model(
        self,
        binding: WorkerBudgetBinding,
        reservation: ModelBudgetReservation,
        raw_usage: object,
        receipt_id: str,
    ) -> None:
        if not isinstance(receipt_id, str) or not receipt_id or len(receipt_id) > 256:
            raise WorkerBudgetError("invalid provider receipt identity")
        prompt, output, total = trusted_usage(raw_usage, reservation)
        receipt = {"id": receipt_id, "prompt": prompt, "output": output, "total": total}
        with self._phase() as c:
            q.remaining(c, self.namespace, binding)
            row = c.execute(
                """SELECT * FROM worker_model_reservations WHERE deployment_namespace=%s
                   AND task_id=%s AND reservation_id=%s FOR UPDATE""",
                (self.namespace, binding.task_id, reservation.reservation_id),
            ).fetchone()
            if (
                row is None
                or row["request_digest"] != reservation.request_digest
                or row["input_upper"] != reservation.input_upper_bound
                or row["output_cap"] != reservation.output_cap
                or row["session_id"] != binding.session_id
                or row["attempt_number"] != binding.attempt_number
                or row["fence"] != binding.fence.model_dump(mode="json")
            ):
                raise WorkerBudgetError("usage conflicts with exact reserved execution")
            if row["receipt"] is not None:
                if row["receipt"] != receipt:
                    raise WorkerBudgetError("immutable provider receipt conflict")
                return
            c.execute(
                """WITH settled AS (
                       UPDATE worker_model_reservations SET receipt=%s
                       WHERE deployment_namespace=%s AND task_id=%s AND reservation_id=%s
                       RETURNING deployment_namespace,task_id
                   )
                   UPDATE worker_task_budgets AS budget
                   SET charged_tokens=budget.charged_tokens-%s FROM settled
                   WHERE budget.deployment_namespace=settled.deployment_namespace
                     AND budget.task_id=settled.task_id""",
                (
                    Jsonb(receipt), self.namespace, binding.task_id, reservation.reservation_id,
                    reservation.token_bound - total,
                ),
            )
            q.remaining(c, self.namespace, binding)

    def reserve_tool(self, binding: WorkerBudgetBinding, call_id: str) -> None:
        UUID(call_id)
        with self._phase() as c:
            q.remaining(c, self.namespace, binding)
            inserted = c.execute(
                """INSERT INTO worker_tool_reservations VALUES(%s,%s,%s)
                   ON CONFLICT DO NOTHING RETURNING call_id""",
                (self.namespace, binding.task_id, call_id),
            ).fetchone()
            if inserted is not None:
                _, child_tools, _ = q.child_charges(c, self.namespace, binding.task_id)
                row = c.execute(
                    """UPDATE worker_task_budgets SET tool_calls=tool_calls+1
                       WHERE deployment_namespace=%s AND task_id=%s
                       AND tool_calls+%s<max_tool_calls
                       RETURNING task_id""",
                    (self.namespace, binding.task_id, child_tools),
                ).fetchone()
                if row is None:
                    raise WorkerBudgetError("Task cumulative tool ceiling exceeded")
            q.remaining(c, self.namespace, binding)

    def current_authority(
        self, connection: Any, binding: WorkerBudgetBinding
    ) -> tuple[BudgetReservation, BudgetReservation]:
        q.remaining(connection, self.namespace, binding)
        row = connection.execute(
            "SELECT * FROM worker_task_budgets WHERE deployment_namespace=%s AND task_id=%s",
            (self.namespace, binding.task_id),
        ).fetchone()
        approved = BudgetReservation(
            model_tokens=max(
                0, min(row["max_model_tokens"], binding.max_model_tokens) - row["charged_tokens"]
            ),
            tool_calls=max(
                0, min(row["max_tool_calls"], binding.max_tool_calls) - row["tool_calls"]
            ),
            runtime_seconds=max(0, int((row["deadline"] - row["started_at"]).total_seconds())),
        )
        free = self.free_budget(connection, binding.task_id)
        assert free is not None
        return approved, free

    def inactive_authority(
        self, connection: Any, task_id: Any, binding_digest: str
    ) -> tuple[BudgetReservation, BudgetReservation] | None:
        row = connection.execute(
            """SELECT b.* FROM worker_task_budgets b JOIN LATERAL
               (SELECT binding_digest FROM task_binding_snapshots WHERE deployment_namespace=
                b.deployment_namespace AND task_id=b.task_id ORDER BY binding_revision DESC LIMIT 1)
               current_binding ON current_binding.binding_digest=b.binding_digest
               WHERE b.deployment_namespace=%s AND b.task_id=%s AND b.binding_digest=%s""",
            (self.namespace, task_id, binding_digest),
        ).fetchone()
        if row is None:
            return None
        approved = BudgetReservation(
            model_tokens=max(0, row["max_model_tokens"] - row["charged_tokens"]),
            tool_calls=max(0, row["max_tool_calls"] - row["tool_calls"]),
            runtime_seconds=max(0, int((row["deadline"] - row["started_at"]).total_seconds())),
        )
        free = self.free_budget(connection, task_id)
        assert free is not None
        return approved, free

    def free_budget(self, connection: Any, task_id: Any) -> BudgetReservation | None:
        row = connection.execute(
            """SELECT *,greatest(0,extract(epoch FROM deadline-clock_timestamp())) AS remaining
               FROM worker_task_budgets WHERE deployment_namespace=%s AND task_id=%s""",
            (self.namespace, task_id),
        ).fetchone()
        if row is None:
            return None
        child_tokens, child_tools, _ = q.child_charges(connection, self.namespace, task_id)
        return BudgetReservation(
            model_tokens=max(0, row["max_model_tokens"] - row["charged_tokens"] - child_tokens),
            tool_calls=max(0, row["max_tool_calls"] - row["tool_calls"] - child_tools),
            runtime_seconds=max(0, int(row["remaining"])),
        )

    def paid_title_allowed(self, session_id: Any) -> bool:
        with self._database.connect() as c:
            row = c.execute(
                """SELECT b.task_id AS guarded_task FROM execution_segments s
                   LEFT JOIN worker_task_budgets b ON b.deployment_namespace=s.deployment_namespace
                     AND b.task_id=s.task_id
                   WHERE s.deployment_namespace=%s AND s.session_id=%s""",
                (self.namespace, session_id),
            ).fetchone()
        # No Task/unknown state cannot authorize an unaccounted paid request.
        return row is not None and row["guarded_task"] is None

    def usage_reader(self, connection: Any, task_id: Any) -> BudgetUsageReceipt | None:
        row = connection.execute(
            """SELECT b.*,p.status,t.active_segment_id,terminal.created_at AS terminal_at,
               terminal.event_type AS terminal_type,
               current_binding.binding_digest AS current_digest
               FROM worker_task_budgets b JOIN agent_tasks t
                 ON t.deployment_namespace=b.deployment_namespace AND t.task_id=b.task_id
               JOIN session_projections p ON p.deployment_namespace=t.deployment_namespace
                 AND p.session_id=t.active_segment_id
               JOIN LATERAL (SELECT binding_digest FROM task_binding_snapshots
                 WHERE deployment_namespace=t.deployment_namespace AND task_id=t.task_id
                 ORDER BY binding_revision DESC LIMIT 1) current_binding ON true
               JOIN LATERAL (SELECT created_at,event_type FROM session_events
                 WHERE deployment_namespace=t.deployment_namespace
                   AND session_id=t.active_segment_id
                   AND event_type IN ('session_completed','session_failed','session_cancelled')
                 ORDER BY sequence DESC LIMIT 1) terminal ON true
               WHERE b.deployment_namespace=%s AND b.task_id=%s""",
            (self.namespace, task_id),
        ).fetchone()
        if (
            row is None
            or row["status"] not in {"completed", "failed", "cancelled"}
            or row["binding_digest"] != row["current_digest"]
            or row["last_session_id"] != row["active_segment_id"]
            or row["terminal_type"] != "session_" + row["status"]
        ):
            return None
        calls = q.model_calls(connection, self.namespace, task_id)
        total = 0
        for call in calls:
            if call["receipt"] is None or str(call["segment_task"]) != str(task_id):
                return None
            try:
                fence = LeaseFence.model_validate(call["fence"])
                if fence.model_dump(mode="json") != call["fence"] or call["attempt_number"] < 1:
                    return None
                receipt = call["receipt"]
                if (
                    not isinstance(receipt, dict)
                    or not isinstance(receipt.get("id"), str)
                    or not receipt["id"]
                ):
                    return None
                usage = {
                    "prompt_tokens": receipt.get("prompt"),
                    "completion_tokens": receipt.get("output"),
                    "total_tokens": receipt.get("total"),
                }
                total += trusted_usage(
                    usage,
                    ModelBudgetReservation(
                        str(call["reservation_id"]),
                        call["request_digest"],
                        call["input_upper"],
                        call["output_cap"],
                    ),
                )[2]
                if (
                    call["session_id"] == row["last_session_id"]
                    and call["attempt_number"] == row["last_attempt"]
                    and call["fence"] != row["last_fence"]
                ):
                    return None
            except ValueError:
                return None
        tools = connection.execute(
            "SELECT count(*) AS count FROM worker_tool_reservations "
            "WHERE deployment_namespace=%s AND task_id=%s",
            (self.namespace, task_id),
        ).fetchone()["count"]
        if (
            total != row["charged_tokens"]
            or tools != row["tool_calls"]
            or not q.tools_confirmed(connection, self.namespace, task_id)
        ):
            return None
        # Conservative wall time includes waiting/restarts. Never infer absent usage as zero.
        seconds = ceil((row["terminal_at"] - row["started_at"]).total_seconds())
        maximum = ceil((row["deadline"] - row["started_at"]).total_seconds())
        if seconds < 0 or seconds > maximum:
            return None
        return BudgetUsageReceipt(
            child_task_ref=str(task_id),
            model_tokens=row["charged_tokens"],
            tool_calls=row["tool_calls"],
            runtime_seconds=seconds,
        )
