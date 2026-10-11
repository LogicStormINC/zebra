"""Fenced attempt reservations and bounded accepted-unit reads."""

from typing import Any

from agent_core.domain.coverage_contracts import (
    CoverageRefusalReason,
    CoverageRefusedError,
    coverage_digest,
)
from agent_core.domain.coverage_execution import CoverageExecutionBudget
from agent_core.domain.coverage_persistence import CoverageRunBinding
from agent_core.domain.coverage_validation import AcceptedCoverageUnit, CoverageUnitKey
from agent_core.domain.events import EventType
from agent_core.domain.leases import LeaseFence
from psycopg.types.json import Jsonb

from agent_storage.postgres.coverage_transactions import (
    append_coverage_event,
    assert_not_certified,
    assert_projection,
    lock_run,
    validate_write,
)


class CoverageExecutionQueries:
    _database: Any
    _deployment: str

    def accepted_for_record(
        self, namespace: str, run_id: str, record_id: str, *, check_id: str | None = None
    ) -> tuple[AcceptedCoverageUnit, ...]:
        results: list[AcceptedCoverageUnit] = []
        cursor = -1
        with self._database.connect() as connection:
            while True:
                rows = connection.execute(
                    """SELECT ordinal,result FROM coverage_units WHERE deployment_namespace=%s
                   AND namespace=%s AND run_id=%s AND unit_key->>'record_id'=%s
                   AND (%s::text IS NULL OR unit_key->>'check_id'=%s)
                   AND result IS NOT NULL AND ordinal>%s ORDER BY ordinal LIMIT 1000""",
                    (self._deployment, namespace, run_id, record_id, check_id, check_id, cursor),
                ).fetchall()
                if not rows:
                    return tuple(results)
                results.extend(AcceptedCoverageUnit.model_validate(row["result"]) for row in rows)
                if len(results) > (4096 + 1) * 32:
                    raise ValueError("record exceeds admitted part/check bounds")
                cursor = int(rows[-1]["ordinal"])

    def reserve_attempt(
        self,
        binding: CoverageRunBinding,
        key: CoverageUnitKey,
        *,
        input_bytes: int,
        budget: CoverageExecutionBudget,
        fence: LeaseFence,
    ) -> int:
        if type(input_bytes) is not int or input_bytes < 0:
            raise ValueError("attempt input byte reservation must be nonnegative")
        with self._database.connect() as connection:
            row, version = lock_run(connection, self._deployment, binding, fence)
            assert_projection(connection, self._deployment, binding, row)
            assert_not_certified(connection, self._deployment, binding)
            if row["cancelled"]:
                raise CoverageRefusedError(CoverageRefusalReason.CANCELLED)
            unit = connection.execute(
                """SELECT result FROM coverage_units WHERE deployment_namespace=%s
                   AND namespace=%s AND run_id=%s AND unit_digest=%s AND unit_key=%s""",
                (
                    self._deployment,
                    binding.namespace,
                    binding.run_id,
                    coverage_digest(key.model_dump(mode="json")),
                    Jsonb(key.model_dump(mode="json")),
                ),
            ).fetchone()
            if unit is None or unit["result"] is not None:
                raise ValueError("attempt does not bind a missing exact coverage unit")
            if row["attempt_budget"] is not None:
                if CoverageExecutionBudget.model_validate(row["attempt_budget"]) != budget:
                    raise ValueError("coverage budget cannot change on restart")
            if (
                row["attempt_count"] >= budget.max_attempts
                or row["input_bytes_count"] + input_bytes > budget.max_input_bytes
            ):
                raise CoverageRefusedError(CoverageRefusalReason.BUDGET_EXCEEDED)
            event = append_coverage_event(
                connection,
                self._deployment,
                binding,
                fence,
                version + 1,
                EventType.COVERAGE_UNIT_ATTEMPTED,
                {
                    "key": key.model_dump(mode="json"),
                    "input_bytes": input_bytes,
                    "budget": budget.model_dump(mode="json"),
                    "attempt_number": int(row["attempt_count"]) + 1,
                },
            )
            connection.execute(
                """UPDATE coverage_runs SET attempt_budget=%s,
                   attempt_count=attempt_count+1,input_bytes_count=input_bytes_count+%s
                   WHERE deployment_namespace=%s AND namespace=%s AND run_id=%s""",
                (
                    Jsonb(budget.model_dump(mode="json")),
                    input_bytes,
                    self._deployment,
                    binding.namespace,
                    binding.run_id,
                ),
            )
            validate_write(connection, self._deployment, binding, fence)
            return event.sequence

    def _rebuild_budget(self, connection: Any, binding: CoverageRunBinding) -> None:
        rows = connection.execute(
            """SELECT payload->'budget' AS budget,count(*) AS attempts,
               coalesce(sum((payload->>'input_bytes')::bigint),0) AS bytes
               FROM session_events WHERE deployment_namespace=%s AND session_id=%s
               AND event_type='coverage_unit_attempted' AND payload->>'namespace'=%s
               AND payload->>'run_id'=%s GROUP BY payload->'budget'""",
            (self._deployment, binding.session_id, binding.namespace, binding.run_id),
        ).fetchall()
        if len(rows) > 1:
            raise ValueError("conflicting durable coverage budget policies")
        if not rows:
            return
        row = rows[0]
        budget = CoverageExecutionBudget.model_validate(row["budget"])
        if row["attempts"] > budget.max_attempts or not 0 <= row["bytes"] <= budget.max_input_bytes:
            raise ValueError("coverage attempt Events violate the frozen budget")
        connection.execute(
            """UPDATE coverage_runs SET attempt_budget=%s,attempt_count=%s,input_bytes_count=%s
               WHERE deployment_namespace=%s AND namespace=%s AND run_id=%s""",
            (
                Jsonb(budget.model_dump(mode="json")),
                row["attempts"],
                row["bytes"],
                self._deployment,
                binding.namespace,
                binding.run_id,
            ),
        )
