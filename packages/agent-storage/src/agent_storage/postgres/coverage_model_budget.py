"""Fenced durable MODEL reservations; exact replay never authorizes transport."""

from contextlib import nullcontext
from datetime import datetime
from typing import Any

from agent_core.domain.coverage_contracts import CoverageRefusalReason, CoverageRefusedError
from agent_core.domain.coverage_model_budget import (
    CoverageModelBudgetState,
    CoverageModelPolicy,
    CoverageModelReservation,
    CoverageModelReservationResult,
    CoverageModelUsageReceipt,
)
from agent_core.domain.coverage_persistence import CoverageRunBinding
from agent_core.domain.coverage_task_admission import coverage_admission_input
from agent_core.domain.events import EventType
from agent_core.domain.leases import LeaseFence
from psycopg.types.json import Jsonb

from agent_storage.postgres.coverage_execution_receipt_read import read_execution_receipt
from agent_storage.postgres.coverage_model_checkpoint import (
    check_checkpoint_retention,
    checkpoint_source,
    verify_model_checkpoint,
    verify_settled_checkpoints,
)
from agent_storage.postgres.coverage_model_index import indexed_call, indexed_state
from agent_storage.postgres.coverage_model_source import (
    params,
    preflight_original_volume,
    replay_model,
    task_policy,
    validate_reservation,
    witness_event,
)
from agent_storage.postgres.coverage_model_summary import summary_state
from agent_storage.postgres.coverage_projection import project_watermark
from agent_storage.postgres.coverage_transactions import (
    append_coverage_event,
    assert_not_certified,
    assert_projection,
    lock_run,
    validate_write,
)
from agent_storage.postgres.work_unit import borrow_work_unit, postgres_work_unit


class CoverageModelBudgetQueries:
    _database: Any
    _deployment: str
    _supported_model_profiles: frozenset[str]
    _artifacts: Any
    _execution_receipts: bool = False
    _execution_receipt_verifier: str | None = None
    _model_observation_deriver: Any = None

    def _model_artifact_scope(self, connection: Any, binding: CoverageRunBinding) -> Any:
        scope = getattr(self._artifacts, "_locked_proof_scope", None)
        return (scope(connection, self._deployment, binding,
                      derive=self._model_observation_deriver)
                if callable(scope) else nullcontext(self._artifacts))

    def _model_boundary(
        self, connection: Any, binding: CoverageRunBinding, fence: LeaseFence
    ) -> int:
        row, version = lock_run(connection, self._deployment, binding, fence)
        assert_projection(connection, self._deployment, binding, row)
        assert_not_certified(connection, self._deployment, binding)
        if row["cancelled"]:
            raise ValueError("cancelled run cannot change model budget")
        return version

    def _model_clock(
        self,
        connection: Any,
        binding: CoverageRunBinding,
        fence: LeaseFence,
        policy: CoverageModelPolicy,
    ) -> None:
        now, digest, _ = validate_write(connection, self._deployment, binding, fence)
        if digest != policy.task_binding_digest:
            raise ValueError("model policy Task binding changed")
        if not policy.started_at <= now < policy.deadline:
            raise CoverageRefusedError(CoverageRefusalReason.BUDGET_EXCEEDED)

    def initialize_model_budget(
        self, binding: CoverageRunBinding, *, fence: LeaseFence
    ) -> CoverageModelPolicy:
        with postgres_work_unit(self._database), self._database.connect() as connection:
            version = self._model_boundary(connection, binding, fence)
            policy = self._receipt_model_policy(connection, binding, fence)
            if policy is not None:
                return policy
            deadlines: list[datetime] = []
            with self._model_artifact_scope(connection, binding) as artifacts:
                state, _ = replay_model(
                    connection, self._deployment, binding,
                    artifacts=artifacts, retention_deadlines=deadlines,
                )
            if state is not None:
                self._model_clock(connection, binding, fence, state.policy)
                check_checkpoint_retention(connection, deadlines)
                return state.policy
            policy = task_policy(connection, self._deployment, binding)
            if policy is None:
                raise ValueError("model budget requires actual strict TaskPrepared admission")
            self._model_clock(connection, binding, fence, policy)
            event = append_coverage_event(
                connection,
                self._deployment,
                binding,
                fence,
                version + 1,
                EventType.COVERAGE_MODEL_BUDGET_INITIALIZED,
                {"policy": policy.model_dump(mode="json")},
            )
            connection.execute(
                "INSERT INTO coverage_model_ledger VALUES (%s,%s,%s,%s,0,0,0)",
                (*params(self._deployment, binding), Jsonb(policy.model_dump(mode="json"))),
            )
            witness_event(connection, self._deployment, binding, event)
            project_watermark(
                connection, self._deployment, binding, event.sequence, cancelled=False
            )
            self._model_clock(connection, binding, fence, policy)
            return policy

    def _receipt_model_policy(
        self, connection: Any, binding: CoverageRunBinding, fence: LeaseFence,
    ) -> CoverageModelPolicy | None:
        # Reuse only the existing qualified native root in this locked transaction.
        # No local budget/count cache and no shortcut for legacy or new MODEL tails.
        if not self._execution_receipts or self._execution_receipt_verifier is None:
            return None
        qualify = getattr(self._artifacts, "_execution_receipt_verifier", None)
        check = getattr(self._artifacts, "check_authority", None)
        if (not callable(qualify) or not callable(check)
                or qualify(self._model_observation_deriver) != self._execution_receipt_verifier):
            return None
        check()
        facts = read_execution_receipt(
            connection, self._deployment, binding, _unchanged_model=True,
        )
        policy = task_policy(connection, self._deployment, binding, incremental=True)
        if facts is None:
            # A bounded batch can settle several calls before its first acceptance
            # receipt. The existing v88 exact native root already seals charges;
            # initializing each invocation must not replay all prior object bytes.
            # This does not certify them: final certification remains independent.
            if policy is None or policy.validation_mode != "final_certification":
                return None
            if summary_state(connection, self._deployment, binding, policy) is None:
                return None
            self._model_clock(connection, binding, fence, policy)
            check()
            self._model_clock(connection, binding, fence, policy)
            return policy
        if facts.verifier_contract != self._execution_receipt_verifier:
            return None
        if policy != facts.budget.policy:
            raise ValueError("receipt model policy conflicts with actual Task admission")
        self._model_clock(connection, binding, fence, facts.budget.policy)
        check_checkpoint_retention(connection, [facts.valid_until])
        check()  # Fresh external authority after proof I/O, before returning policy.
        self._model_clock(connection, binding, fence, facts.budget.policy)
        check_checkpoint_retention(connection, [facts.valid_until])
        return facts.budget.policy

    def reserve_model_call(
        self,
        binding: CoverageRunBinding,
        reservation: CoverageModelReservation,
        *,
        fence: LeaseFence,
    ) -> CoverageModelReservationResult:
        reservation = CoverageModelReservation.model_validate(coverage_admission_input(reservation))
        with postgres_work_unit(self._database), self._database.connect() as connection:
            version = self._model_boundary(connection, binding, fence)
            deadlines: list[datetime] = []
            state = indexed_state(connection, self._deployment, binding)
            if reservation.model_profile not in self._supported_model_profiles:
                raise ValueError("unsupported configured model request-bound profile")
            validate_reservation(connection, self._deployment, binding, state.policy, reservation)
            self._model_clock(connection, binding, fence, state.policy)
            previous = indexed_call(
                connection, self._deployment, binding, reservation.reservation_key
            )
            preflight_original_volume(
                connection, self._deployment, binding, retention_deadlines=deadlines,
                _incremental_keys=(
                    set() if state.policy.validation_mode == "final_certification" else None
                ),
                _policy=state.policy,
            )
            if previous is not None:
                if previous["reservation"] != reservation.model_dump(mode="json"):
                    raise ValueError(
                        "model reservation key reused with changed request/unit/admission"
                    )
                if previous["receipt"] is not None:
                    with self._model_artifact_scope(connection, binding) as artifacts:
                        verify_model_checkpoint(
                            connection, self._deployment, binding,
                            CoverageModelUsageReceipt.model_validate(previous["receipt"]),
                            artifacts, reserved_sequence=previous["reserved_sequence"],
                            receipt_sequence=previous["receipt_sequence"],
                            retention_deadlines=deadlines,
                        )
                self._model_clock(connection, binding, fence, state.policy)
                check_checkpoint_retention(connection, deadlines)
                return CoverageModelReservationResult(
                    reservation=reservation,
                    event_watermark=previous["reserved_sequence"],
                    invoke=False,
                    receipt=previous["receipt"],
                )
            unit = connection.execute(
                """SELECT result FROM coverage_units WHERE deployment_namespace=%s AND namespace=%s
                   AND run_id=%s AND unit_key=%s""",
                (
                    *params(self._deployment, binding),
                    Jsonb(reservation.key.model_dump(mode="json")),
                ),
            ).fetchone()
            if unit is None or unit["result"] is not None:
                raise ValueError("model invocation requires a missing exact unit")
            if (
                state.calls >= state.policy.max_calls
                or state.charged_tokens + reservation.token_bound > state.policy.max_tokens
            ):
                raise CoverageRefusedError(CoverageRefusalReason.BUDGET_EXCEEDED)
            if state.policy.validation_mode == "eager":
                verify_settled_checkpoints(
                    connection,
                    self._deployment,
                    binding,
                    self._artifacts,
                    retention_deadlines=deadlines,
                )
            event = append_coverage_event(
                connection,
                self._deployment,
                binding,
                fence,
                version + 1,
                EventType.COVERAGE_MODEL_CALL_RESERVED,
                {"reservation": reservation.model_dump(mode="json")},
            )
            connection.execute(
                "INSERT INTO coverage_model_calls VALUES (%s,%s,%s,%s,%s,%s,NULL,NULL)",
                (
                    *params(self._deployment, binding),
                    reservation.reservation_key,
                    Jsonb(reservation.model_dump(mode="json")),
                    event.sequence,
                ),
            )
            witness_event(connection, self._deployment, binding, event)
            connection.execute(
                """UPDATE coverage_model_ledger SET calls=calls+1,
                   charged_tokens=charged_tokens+%s,unresolved=unresolved+1
                   WHERE deployment_namespace=%s AND namespace=%s AND run_id=%s""",
                (reservation.token_bound, *params(self._deployment, binding)),
            )
            project_watermark(
                connection, self._deployment, binding, event.sequence, cancelled=False
            )
            self._model_clock(connection, binding, fence, state.policy)
            check_checkpoint_retention(connection, deadlines)
            return CoverageModelReservationResult(
                reservation=reservation, event_watermark=event.sequence, invoke=True
            )

    def record_model_usage(
        self, binding: CoverageRunBinding, receipt: CoverageModelUsageReceipt, *, fence: LeaseFence
    ) -> int:
        return self._settle_model_checkpoint(binding, receipt, fence=fence)[0]

    def settle_model_checkpoint(
        self, binding: CoverageRunBinding, receipt: CoverageModelUsageReceipt, *, fence: LeaseFence
    ) -> tuple[int, bytes]:
        if borrow_work_unit((self._database._dsn, self._deployment)) is not None:
            raise ValueError("verified MODEL delivery requires its own completed transaction")
        # Preserve custom acknowledgement/crash hooks on the existing Port. The
        # native method uses one operation; altered delegates require fresh
        # idempotent proof after their callback, never inherit verified delivery.
        previous: int | None = None
        if ("record_model_usage" in vars(self)
                or type(self).record_model_usage is not _NATIVE_RECORD_USAGE):
            previous = self.record_model_usage(binding, receipt, fence=fence)
            if type(previous) is not int or previous < 1:
                raise ValueError("custom MODEL acknowledgement is not a positive sequence")
        result = self._settle_model_checkpoint(binding, receipt, fence=fence)
        if previous is not None and previous != result[0]:
            raise ValueError("custom MODEL acknowledgement conflicts with verified settlement")
        return result

    def _settle_model_checkpoint(
        self, binding: CoverageRunBinding, receipt: CoverageModelUsageReceipt, *, fence: LeaseFence
    ) -> tuple[int, bytes]:
        # Validate raw/forged typed fields before mutation. Invalid/absent usage
        # leaves the existing full charge and unresolved reservation intact.
        receipt = CoverageModelUsageReceipt.model_validate(coverage_admission_input(receipt))
        with postgres_work_unit(self._database), self._database.connect() as connection:
            version = self._model_boundary(connection, binding, fence)
            deadlines: list[datetime] = []
            state = indexed_state(connection, self._deployment, binding)
            if (
                state is None
                or receipt.reservation.model_profile not in self._supported_model_profiles
            ):
                raise ValueError("unsupported/uninitialized model usage")
            self._model_clock(connection, binding, fence, state.policy)
            call = indexed_call(
                connection, self._deployment, binding, receipt.reservation.reservation_key
            )
            if call is None or call["reservation"] != receipt.reservation.model_dump(mode="json"):
                raise ValueError("usage does not match an exact reserved request")
            proof: list[tuple[Any, Any]] = []
            with self._model_artifact_scope(connection, binding) as artifacts:
                preflight_original_volume(
                    connection, self._deployment, binding, candidate=receipt,
                    reserved_sequence=call["reserved_sequence"], retention_deadlines=deadlines,
                    _incremental_keys=(
                        {receipt.reservation.key}
                        if state.policy.validation_mode == "final_certification" else None
                    ),
                    _policy=state.policy, _artifacts=artifacts,
                )
                body = verify_model_checkpoint(
                    connection, self._deployment, binding, receipt, artifacts,
                    reserved_sequence=call["reserved_sequence"],
                    receipt_sequence=call["receipt_sequence"], retention_deadlines=deadlines,
                    proof=proof,
                )
            # The scope exit invokes extensible authority callbacks. Row locks
            # do not stop same-transaction writes: bypass its cached reader and
            # compare the full current lifecycle and canonical Event afterward.
            fresh: list[tuple[Any, Any]] = []
            checkpoint_source(
                connection, self._deployment, binding, receipt,
                reserved_sequence=call["reserved_sequence"],
                receipt_sequence=call["receipt_sequence"], proof=fresh,
            )
            if fresh != proof:
                raise ValueError("checkpoint proof changed during settlement callback")
            if call["receipt"] is not None:
                if call["receipt"] != receipt.model_dump(mode="json"):
                    raise ValueError("conflicting model usage receipt")
                self._model_clock(connection, binding, fence, state.policy)
                check_checkpoint_retention(connection, deadlines)
                return int(call["receipt_sequence"]), body
            event = append_coverage_event(
                connection,
                self._deployment,
                binding,
                fence,
                version + 1,
                EventType.COVERAGE_MODEL_USAGE_RECORDED,
                {"receipt": receipt.model_dump(mode="json")},
            )
            connection.execute(
                """UPDATE coverage_model_calls SET receipt=%s,receipt_sequence=%s
                   WHERE deployment_namespace=%s AND namespace=%s AND run_id=%s
                   AND reservation_key=%s""",
                (
                    Jsonb(receipt.model_dump(mode="json")),
                    event.sequence,
                    *params(self._deployment, binding),
                    receipt.reservation.reservation_key,
                ),
            )
            witness_event(connection, self._deployment, binding, event)
            connection.execute(
                """UPDATE coverage_model_ledger SET charged_tokens=charged_tokens-%s,
                   unresolved=unresolved-1 WHERE deployment_namespace=%s
                   AND namespace=%s AND run_id=%s""",
                (
                    receipt.reservation.token_bound - receipt.total_tokens,
                    *params(self._deployment, binding),
                ),
            )
            project_watermark(
                connection, self._deployment, binding, event.sequence, cancelled=False
            )
            self._model_clock(connection, binding, fence, state.policy)
            check_checkpoint_retention(connection, deadlines)
            return event.sequence, body

    def model_budget_state(self, binding: CoverageRunBinding) -> CoverageModelBudgetState:
        with postgres_work_unit(self._database), self._database.connect() as connection:
            row, _ = lock_run(connection, self._deployment, binding, None)
            assert_projection(connection, self._deployment, binding, row)
            deadlines: list[datetime] = []
            policy = task_policy(connection, self._deployment, binding, incremental=True)
            state: CoverageModelBudgetState | None
            if policy is not None and policy.validation_mode == "final_certification":
                state = indexed_state(connection, self._deployment, binding, _policy=policy)
                preflight_original_volume(
                    connection, self._deployment, binding, retention_deadlines=deadlines,
                    _incremental_keys=set(),
                    _policy=policy,
                )
            else:
                state, _ = replay_model(
                    connection,
                    self._deployment,
                    binding,
                    artifacts=self._artifacts,
                    retention_deadlines=deadlines,
                )
            if state is None:
                raise ValueError("model ledger is not initialized")
            check_checkpoint_retention(connection, deadlines)
            return state


_NATIVE_RECORD_USAGE = CoverageModelBudgetQueries.record_model_usage
