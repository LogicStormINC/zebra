"""Exact source replay and independent witnesses; no refund from missing evidence."""
from datetime import datetime, timedelta
from types import EllipsisType
from typing import Any

from agent_core.application.coverage_admission import validate_coverage_admission
from agent_core.contracts.task_prepared import TaskPreparedPayload
from agent_core.domain.coverage_contracts import coverage_digest
from agent_core.domain.coverage_model_budget import (
    CoverageModelBudgetState,
    CoverageModelPolicy,
    CoverageModelReservation,
    CoverageModelUsageReceipt,
)
from agent_core.domain.coverage_persistence import CoverageRunBinding
from agent_core.domain.coverage_validation import CoverageUnitKey
from agent_core.domain.events import EventType, SessionEvent
from agent_core.domain.task_bindings import TaskBindingSnapshot
from psycopg.types.json import Jsonb

from agent_storage.postgres.coverage_artifacts import (
    MAX_COVERAGE_ARTIFACT_BYTES as MAX_COVERAGE_ARTIFACT_BYTES,
)
from agent_storage.postgres.coverage_model_certificate import (
    certify_model_budget as certify_model_budget,
)
from agent_storage.postgres.coverage_model_checkpoint import (
    check_checkpoint_retention as check_checkpoint_retention,
)
from agent_storage.postgres.coverage_model_checkpoint import (
    checkpoint_source as checkpoint_source,
)
from agent_storage.postgres.coverage_model_checkpoint import (
    verify_model_checkpoint,
)
from agent_storage.postgres.coverage_model_replay_rows import (
    indexed_calls,
    model_rows,
    task_events,
)
from agent_storage.postgres.coverage_model_replay_rows import (
    original_rows as original_rows,
)
from agent_storage.postgres.coverage_model_volume import (
    preflight_original_volume as preflight_original_volume,
)
from agent_storage.postgres.coverage_task_summary import admitted_task_origin
from agent_storage.postgres.coverage_transactions import manifest_event, validate_event_fence

MODEL_TYPES = (
    EventType.COVERAGE_MODEL_BUDGET_INITIALIZED,
    EventType.COVERAGE_MODEL_CALL_RESERVED,
    EventType.COVERAGE_MODEL_USAGE_RECORDED,
)


def params(deployment: str, binding: CoverageRunBinding) -> tuple[str, str, str]:
    return deployment, binding.namespace, binding.run_id


def task_policy(
    connection: Any, deployment: str, binding: CoverageRunBinding, *, incremental: bool = False,
) -> CoverageModelPolicy | None:
    origin = admitted_task_origin(connection, deployment, binding) if incremental else None
    if origin is not None:
        return _policy_from_origin(connection, deployment, binding, origin)
    # Only Task descriptors cross this boundary; message/tool bodies stay in PG.
    origin = raw = None
    conflict = False
    for event in task_events(connection, deployment, binding):
        if origin is None and event.payload.get("coverage_admission") is None:
            conflict = True  # A legacy prefix is allowed only if no strict admission follows.
            continue
        task = TaskPreparedPayload.model_validate(event.payload)
        if raw is None:
            origin, raw = event, task
        conflict |= task.coverage_admission != raw.coverage_admission
        conflict |= task.host_context != raw.host_context
    if origin is None or raw is None:
        return None
    if conflict:
        raise ValueError("persisted strict Task identity changed or disappeared")
    history = connection.execute(
        """SELECT s.current_version,h.count,h.first,h.last FROM session_streams s
           CROSS JOIN LATERAL (
             SELECT count(*) AS count,min(sequence) AS first,max(sequence) AS last
             FROM session_events e WHERE e.deployment_namespace=s.deployment_namespace
               AND e.session_id=s.session_id
           ) h WHERE s.deployment_namespace=%s AND s.session_id=%s""",
        (deployment, binding.session_id),
    ).fetchone()
    if (
        history is None
        or history["first"] != 0
        or history["last"] != history["current_version"]
        or history["count"] != history["current_version"] + 1
    ):
        raise ValueError("model budget requires unpruned exact Session history")
    return _policy_from_origin(connection, deployment, binding, origin)


def _policy_from_origin(
    connection: Any, deployment: str, binding: CoverageRunBinding, origin: SessionEvent,
) -> CoverageModelPolicy:
    raw = TaskPreparedPayload.model_validate(origin.payload)
    admission = validate_coverage_admission(
        raw.coverage_admission, host_context=raw.host_context, now=origin.created_at
    )
    authority = connection.execute(
        """SELECT snapshot_json,binding_digest FROM task_binding_snapshots
           WHERE deployment_namespace=%s AND task_id=%s ORDER BY binding_revision DESC LIMIT 1""",
        (deployment, binding.task_id),
    ).fetchone()
    if authority is None:
        raise ValueError("model budget has no persisted Task binding")
    task_binding = TaskBindingSnapshot.model_validate(authority["snapshot_json"])
    if (
        task_binding.task_id != str(binding.task_id)
        or task_binding.binding_digest != authority["binding_digest"]
        or task_binding.host_capability.host_context != raw.host_context
        or admission.contract != binding.contract
        or binding.snapshot.source_resource_ref != admission.source_resource.resource_id
    ):
        raise ValueError("model admission disagrees with run/history/Task binding")
    return CoverageModelPolicy(
        admission_event_digest=coverage_digest(origin.model_dump(mode="json")),
        admission_digest=coverage_digest(admission.model_dump(mode="json")),
        task_binding_digest=task_binding.binding_digest,
        model_profile=admission.model_profile,
        validation_mode=admission.validation_mode,
        max_calls=admission.max_model_calls,
        max_tokens=admission.max_model_tokens,
        max_runtime_seconds=admission.max_runtime_seconds,
        started_at=origin.created_at,
        deadline=origin.created_at + timedelta(seconds=admission.max_runtime_seconds),
    )


def validate_reservation(
    connection: Any,
    deployment: str,
    binding: CoverageRunBinding,
    policy: CoverageModelPolicy,
    reservation: CoverageModelReservation,
    *,
    source_keys: set[CoverageUnitKey] | None = None,
) -> None:
    if (
        reservation.admission_digest != policy.admission_digest
        or reservation.model_profile != policy.model_profile
    ):
        raise ValueError("model reservation admission/profile conflicts")
    key = reservation.key
    if key.kind != "part" or not any(
        check.kind == "model"
        and check.id == key.check_id
        and check.version == key.check_version
        and check.definition_digest == key.definition_digest
        for check in binding.contract.checks
    ):
        raise ValueError("model reservation requires an admitted MODEL part unit")
    if source_keys is not None:
        if key not in source_keys:
            raise ValueError("model reservation unit/source conflicts")
        return
    source = connection.execute(
        """SELECT 1 FROM coverage_units WHERE deployment_namespace=%s AND namespace=%s
           AND run_id=%s AND unit_digest=%s AND unit_key=%s""",
        (
            *params(deployment, binding),
            coverage_digest(key.model_dump(mode="json")),
            Jsonb(key.model_dump(mode="json")),
        ),
    ).fetchone()
    if source is None:
        raise ValueError("model reservation unit/source conflicts")


def replay_model(
    connection: Any,
    deployment: str,
    binding: CoverageRunBinding,
    *,
    rebuild: bool = False,
    source_keys: set[CoverageUnitKey] | None = None,
    artifacts: Any = None,
    retention_deadlines: list[datetime] | None = None,
    _incremental_keys: set[CoverageUnitKey] | None = None,
    _policy: CoverageModelPolicy | None | EllipsisType = ...,
) -> tuple[CoverageModelBudgetState | None, dict[str, Any]]:
    deadlines = [] if retention_deadlines is None else retention_deadlines
    # ponytail: only the enclosing locked proof passes its native policy; no
    # transaction-global cache. Standalone callers and new phases derive afresh.
    policy = task_policy(connection, deployment, binding) if _policy is ... else _policy
    if _incremental_keys is not None and (
        rebuild or policy is None or policy.validation_mode != "final_certification"
    ):
        raise ValueError("incremental proof requires explicit admission and cannot rebuild")
    indexed_budget = None
    record_ids = None
    if _incremental_keys is not None:
        from agent_storage.postgres.coverage_model_index import indexed_state

        # Native source/index integrity still covers the whole ledger. Only the
        # Python transcript and physical proof are delta-scoped; final/recovery
        # never use this branch. No counter-only shortcut or history cache.
        indexed_budget = indexed_state(connection, deployment, binding, _policy=policy)
        record_ids = sorted({key.record_id for key in _incremental_keys})
    if _incremental_keys is None:
        preflight_original_volume(
            connection, deployment, binding, retention_deadlines=deadlines, _artifacts=artifacts,
        )
    else:
        preflight_original_volume(
            connection, deployment, binding, retention_deadlines=deadlines,
            _incremental_keys=_incremental_keys,
            _policy=policy,
            _artifacts=artifacts,
        )
    ledger = None if indexed_budget is not None else connection.execute(
        """SELECT * FROM coverage_model_ledger
           WHERE deployment_namespace=%s AND namespace=%s AND run_id=%s""",
        params(deployment, binding),
    ).fetchone()
    # indexed_state already checks the global source/witness/index and counters
    # in this locked phase. Do not repeat those aggregate reads for a delta.
    witnesses = {"count": 0, "conflict": False, "missing": False} if (
        indexed_budget is not None
    ) else connection.execute(
        """SELECT count(*) AS count,
           coalesce(bool_or(coverage_model_event_source(to_jsonb(e)) IS DISTINCT FROM
             coverage_model_event_source(w.source_row)),false) AS conflict
           ,coalesce(bool_or(e.event_type IS NULL OR NOT(e.event_type=ANY(%s))
             OR e.payload->>'namespace' IS DISTINCT FROM %s
             OR e.payload->>'run_id' IS DISTINCT FROM %s),false) AS missing
           FROM coverage_model_events w LEFT JOIN session_events e
             ON e.deployment_namespace=w.deployment_namespace AND e.session_id=%s
             AND e.sequence=w.sequence
           WHERE w.deployment_namespace=%s AND w.namespace=%s AND w.run_id=%s""",
        (
            list(MODEL_TYPES),
            binding.namespace,
            binding.run_id,
            binding.session_id,
            *params(deployment, binding),
        ),
    ).fetchone()
    if witnesses["conflict"]:
        raise ValueError("model source proof witness conflicts")
    if witnesses["missing"]:
        raise ValueError("model source Event missing or tampered; charges cannot be reset")
    if witnesses["count"] > 400001:
        raise ValueError("model projection/source exceeds bounded replay count")
    manifest = manifest_event(connection, deployment, binding.namespace, binding.run_id)
    calls: dict[str, Any] = {}
    initialized = False
    charged = 0
    last_sequence = -1
    for row in model_rows(
        connection, deployment, binding, MODEL_TYPES, record_ids=record_ids, artifacts=artifacts,
    ):
        witness_digest = row.pop("witness_digest")
        event = SessionEvent.model_validate(row)
        if witness_digest is not None and witness_digest != coverage_digest(
            event.model_dump(mode="json")
        ):
            raise ValueError("model source Event missing or tampered; charges cannot be reset")
        if not rebuild and witness_digest is None:
            raise ValueError("model source/projection witness conflict; rebuild required")
        if last_sequence < 0 and (
            policy is None or manifest is None or event.sequence <= manifest["sequence"]
        ):
            raise ValueError("model Events have no exact admitted manifest")
        assert policy is not None
        last_sequence = event.sequence
        validate_event_fence(event.payload)
        if event.actor.value != "system" or event.session_id != binding.session_id:
            raise ValueError("invalid model source Event identity")
        payload = {
            name: value
            for name, value in event.payload.items()
            if name not in {"namespace", "run_id", "fence"}
        }
        if event.event_type == EventType.COVERAGE_MODEL_BUDGET_INITIALIZED:
            if (
                initialized
                or set(payload) != {"policy"}
                or CoverageModelPolicy.model_validate(payload["policy"]) != policy
            ):
                raise ValueError("frozen model policy source conflicts")
            initialized = True
        elif not initialized:
            raise ValueError("model calls preceded budget initialization")
        elif event.event_type == EventType.COVERAGE_MODEL_CALL_RESERVED:
            if set(payload) != {"reservation"}:
                raise ValueError("invalid model reservation Event")
            reservation = CoverageModelReservation.model_validate(payload["reservation"])
            validate_reservation(
                connection, deployment, binding, policy, reservation, source_keys=source_keys
            )
            if reservation.reservation_key in calls:
                raise ValueError("duplicate model reservation source")
            calls[reservation.reservation_key] = {
                "reservation": reservation.model_dump(mode="json"),
                "reserved_sequence": event.sequence,
                "receipt": None,
                "receipt_sequence": None,
            }
            charged += reservation.token_bound
        else:
            if set(payload) != {"receipt"}:
                raise ValueError("invalid model usage Event")
            receipt = CoverageModelUsageReceipt.model_validate(payload["receipt"])
            call = calls.get(receipt.reservation.reservation_key)
            if (
                call is None
                or call["receipt"] is not None
                or call["reservation"] != receipt.reservation.model_dump(mode="json")
            ):
                raise ValueError("model receipt has no matching unresolved reservation")
            if artifacts is None:
                raise ValueError("settled MODEL replay requires a governed Artifact reader")
            if _incremental_keys is None or receipt.reservation.key in _incremental_keys:
                verify_model_checkpoint(
                    connection, deployment, binding, receipt, artifacts,
                    reserved_sequence=call["reserved_sequence"],
                    receipt_sequence=event.sequence, retention_deadlines=deadlines,
                )
            call.update(receipt=receipt.model_dump(mode="json"), receipt_sequence=event.sequence)
            charged -= receipt.reservation.token_bound - receipt.total_tokens
        if (
            event.created_at < policy.started_at
            or event.created_at >= policy.deadline
            or len(calls) > policy.max_calls
            or charged > policy.max_tokens
        ):
            raise ValueError("model source violates frozen deadline/limits")
        if rebuild:
            witness_event(connection, deployment, binding, event)
    index_count = 0
    for call in indexed_calls(connection, deployment, binding, record_ids=record_ids):
        index_count += 1
        if calls.get(call["reservation_key"]) != {
            name: call[name]
            for name in ("reservation", "reserved_sequence", "receipt", "receipt_sequence")
        }:
            raise ValueError("model call index conflicts with exact source Events")
    if last_sequence < 0:
        if indexed_budget is not None or ledger or witnesses["count"] or index_count:
            raise ValueError("model ledger lost initialized source Events")
        return None, {}
    assert policy is not None
    if ledger is not None and ledger["policy"] != policy.model_dump(mode="json"):
        raise ValueError("frozen model ledger policy conflicts")
    if not rebuild and (
        (ledger is None and indexed_budget is None) or index_count != len(calls)
    ):
        raise ValueError("model ledger projection missing; rebuild required")
    state = indexed_budget or CoverageModelBudgetState(
        policy=policy,
        calls=len(calls),
        charged_tokens=charged,
        unresolved=sum(call["receipt"] is None for call in calls.values()),
    )
    if ledger is not None and (ledger["calls"], ledger["charged_tokens"], ledger["unresolved"]) != (
        state.calls,
        state.charged_tokens,
        state.unresolved,
    ):
        raise ValueError("model ledger counters conflict with exact source Events")
    certificates = connection.execute(
        """SELECT sequence,created_at FROM session_events
           WHERE deployment_namespace=%s AND session_id=%s
           AND event_type='coverage_report_certified'
           AND payload->>'namespace'=%s AND payload->>'run_id'=%s""",
        (deployment, binding.session_id, binding.namespace, binding.run_id),
    ).fetchall()
    if certificates and (
        len(certificates) != 1
        or state.unresolved
        or last_sequence >= certificates[0]["sequence"]
        or not policy.started_at <= certificates[0]["created_at"] < policy.deadline
    ):
        raise ValueError("model budget proof conflicts with historical certification")
    check_checkpoint_retention(connection, deadlines)
    if rebuild:
        connection.execute(
            """INSERT INTO coverage_model_ledger VALUES (%s,%s,%s,%s,%s,%s,%s)
               ON CONFLICT DO NOTHING""",
            (
                *params(deployment, binding),
                Jsonb(policy.model_dump(mode="json")),
                state.calls,
                state.charged_tokens,
                state.unresolved,
            ),
        )
        for key, call in calls.items():
            connection.execute(
                """INSERT INTO coverage_model_calls VALUES (%s,%s,%s,%s,%s,%s,%s,%s)
                   ON CONFLICT DO NOTHING""",
                (
                    *params(deployment, binding),
                    key,
                    Jsonb(call["reservation"]),
                    call["reserved_sequence"],
                    Jsonb(call["receipt"]) if call["receipt"] is not None else None,
                    call["receipt_sequence"],
                ),
            )
    check_checkpoint_retention(connection, deadlines)
    return state, calls


def witness_event(
    connection: Any, deployment: str, binding: CoverageRunBinding, event: SessionEvent
) -> None:
    connection.execute(
        """INSERT INTO coverage_model_events
           SELECT %s,%s,%s,%s,%s,to_jsonb(e) FROM session_events e
           WHERE deployment_namespace=%s AND session_id=%s AND sequence=%s
           ON CONFLICT DO NOTHING""",
        (
            *params(deployment, binding),
            event.sequence,
            coverage_digest(event.model_dump(mode="json")),
            deployment,
            binding.session_id,
            event.sequence,
        ),
    )
