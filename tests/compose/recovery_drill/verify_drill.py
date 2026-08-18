"""Run a local fenced outbox rollback, reconciliation and race drill."""

from __future__ import annotations

import argparse
import json
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta
from hashlib import sha256
from pathlib import Path
from time import perf_counter
from typing import Any
from uuid import uuid4

import psycopg
from agent_core.domain.effect_dispatch import (
    EffectDispatchStateError,
    EffectDispatchStatus,
    EffectEvidence,
    EffectResolutionOutcome,
    EffectScheduleRequest,
)
from agent_core.domain.events import EventActor, EventType, SessionEvent
from agent_core.domain.identifiers import SessionId, new_event_id, new_session_id, new_tool_call_id
from agent_core.domain.leases import LeaseLostError
from agent_core.domain.session_handoff import EffectIdentity
from agent_core.domain.tools import ToolCallStatus, ToolResult
from agent_storage import (
    PostgresEffectDispatchStore,
    PostgresLeaseStore,
    apply_postgres_migrations,
    bootstrap_control_plane_epoch,
    rotate_control_plane_epoch,
)

NAMESPACE = "recovery-drill"


def _event(session_id: SessionId, sequence: int, event_type: EventType) -> SessionEvent:
    return SessionEvent(
        event_id=new_event_id(),
        session_id=session_id,
        sequence=sequence,
        event_type=event_type,
        payload={},
        actor=EventActor.TOOL,
        created_at=datetime.now(UTC),
        idempotency_key=f"recovery-drill-{event_type.value}-{sequence}-{uuid4()}",
    )


def _request(session_id: SessionId, sequence: int, suffix: str) -> EffectScheduleRequest:
    return EffectScheduleRequest(
        root_session_id=session_id,
        identity=EffectIdentity(
            authority_scope_hash="recovery-drill-authority",
            tool_name=f"recovery-{suffix}",
            operation_kind="create",
            target_hash="recovery-drill-target",
            canonical_effect_hash=f"effect-{suffix}",
            external_operation_id_hash=f"provider-{suffix}",
        ),
        request_hash=sha256(suffix.encode()).hexdigest(),
        payload_artifact_ref=f"artifact://recovery-drill/{suffix}",
        started_event=_event(session_id, sequence, EventType.TOOL_EXECUTION_STARTED),
    )


def _evidence(reason: str) -> EffectEvidence:
    return EffectEvidence(reason_code=reason, provider_operation_id_hash="c" * 64)


def _result() -> ToolResult:
    return ToolResult(
        tool_call_id=new_tool_call_id(),
        status=ToolCallStatus.EXECUTED,
        output="created",
        metadata={"provider_operation_id_hash": "c" * 64},
    )


def _store(dsn: str) -> PostgresEffectDispatchStore:
    return PostgresEffectDispatchStore(dsn, deployment_namespace=NAMESPACE)


def _lease_store(dsn: str) -> PostgresLeaseStore:
    return PostgresLeaseStore(dsn, deployment_namespace=NAMESPACE)


def _row_count(dsn: str, table: str) -> int:
    if table not in {"effect_outbox", "session_events"}:
        raise ValueError("unsupported drill count table")
    with psycopg.connect(dsn) as connection:
        row = connection.execute(
            f"SELECT count(*) FROM {table} WHERE deployment_namespace = %s",
            (NAMESPACE,),
        ).fetchone()
    if row is None:
        raise RuntimeError(f"missing count row for {table}")
    return int(row[0])


def _delete_namespace(dsn: str) -> None:
    with psycopg.connect(dsn) as connection:
        for table in (
            "effect_outbox",
            "session_events",
            "session_streams",
            "worker_leases",
            "control_plane_epochs",
        ):
            connection.execute(
                f"DELETE FROM {table} WHERE deployment_namespace = %s",
                (NAMESPACE,),
            )


def _run(dsn: str) -> dict[str, Any]:
    apply_postgres_migrations(dsn)
    bootstrap_control_plane_epoch(dsn, deployment_namespace=NAMESPACE)
    session_id = new_session_id()
    leases = _lease_store(dsn)
    first_lease = leases.acquire(
        session_id,
        owner_instance_id="worker-a",
        ttl=timedelta(seconds=30),
    )
    store = _store(dsn)

    invalid = _request(session_id, sequence=99, suffix="rollback")
    try:
        store.schedule(invalid, fence=first_lease.fence)
    except ValueError:
        pass
    else:
        raise RuntimeError("invalid Event sequence unexpectedly wrote an Effect")
    if _row_count(dsn, "effect_outbox") != 0 or _row_count(dsn, "session_events") != 0:
        raise RuntimeError("failed schedule did not roll back Event/outbox writes")

    dispatch = store.schedule(
        _request(session_id, sequence=0, suffix="crash-race"),
        fence=first_lease.fence,
    )
    race_started = perf_counter()
    with ThreadPoolExecutor(max_workers=2) as executor:
        claims = tuple(
            executor.map(
                lambda candidate: candidate.claim_next(
                    session_id,
                    fence=first_lease.fence,
                    claim_ttl=timedelta(seconds=30),
                ),
                (store, _store(dsn)),
            )
        )
    race_ms = (perf_counter() - race_started) * 1_000
    if sum(claim is not None for claim in claims) != 1:
        raise RuntimeError("same-dispatch worker race did not produce one winner")
    old_claim = next(claim for claim in claims if claim is not None)

    recovery_started = perf_counter()
    new_epoch = rotate_control_plane_epoch(dsn, deployment_namespace=NAMESPACE)
    second_lease = leases.acquire(
        session_id,
        owner_instance_id="worker-b",
        ttl=timedelta(seconds=30),
    )
    if second_lease.fence.control_plane_epoch != new_epoch:
        raise RuntimeError("replacement worker did not receive the rotated epoch")
    candidates = store.list_reconcilable(session_id, current_fence=second_lease.fence)
    if len(candidates) != 1 or candidates[0].dispatch.dispatch_id != dispatch.dispatch_id:
        raise RuntimeError("replacement worker did not discover the stale claim")

    try:
        store.complete(
            old_claim,
            result=_result(),
            terminal_event=_event(session_id, 1, EventType.TOOL_EXECUTION_COMPLETED),
        )
    except LeaseLostError:
        stale_terminal_rejected = True
    else:
        stale_terminal_rejected = False
    if not stale_terminal_rejected:
        raise RuntimeError("stale worker terminal write was accepted")

    def reconcile(candidate: PostgresEffectDispatchStore) -> object:
        try:
            return candidate.reconcile_expired(
                old_claim.dispatch.dispatch_id,
                old_claim=candidates[0],
                current_fence=second_lease.fence,
                evidence=_evidence("worker_crash_epoch_replaced"),
            )
        except EffectDispatchStateError as error:
            return error

    with ThreadPoolExecutor(max_workers=2) as executor:
        reconciliations = tuple(executor.map(reconcile, (store, _store(dsn))))
    uncertain = tuple(
        result
        for result in reconciliations
        if getattr(result, "status", None) is EffectDispatchStatus.UNCERTAIN
    )
    if len(uncertain) != 1:
        raise RuntimeError("concurrent reconciliation did not produce one uncertain winner")
    if sum(isinstance(result, EffectDispatchStateError) for result in reconciliations) != 1:
        raise RuntimeError("concurrent reconciliation did not reject the loser")

    if store.claim_next(session_id, fence=second_lease.fence, claim_ttl=timedelta(seconds=30)):
        raise RuntimeError("uncertain Effect silently returned to pending")
    terminal = _event(session_id, 1, EventType.TOOL_EXECUTION_FAILED)
    store.resolve_uncertain(
        dispatch.dispatch_id,
        current_fence=second_lease.fence,
        evidence=_evidence("provider_proved_no_effect"),
        outcome=EffectResolutionOutcome.FAILED_NO_EFFECT,
        terminal_event=terminal,
    )
    recovery_ms = (perf_counter() - recovery_started) * 1_000
    if _row_count(dsn, "effect_outbox") != 1 or _row_count(dsn, "session_events") != 2:
        raise RuntimeError("recovery Event/outbox counts do not show zero durable loss")
    return {
        "scope": "local-only",
        "dispatch_id": str(dispatch.dispatch_id),
        "claim_winner_count": 1,
        "reconciliation_winner_count": 1,
        "stale_terminal_rejected": stale_terminal_rejected,
        "rollback_outbox_count": 0,
        "rollback_event_count": 0,
        "final_dispatch_status": EffectDispatchStatus.FAILED_NO_EFFECT.value,
        "durable_event_count": 2,
        "outbox_count": 1,
        "rpo_events_lost": 0,
        "observed_claim_race_ms": round(race_ms, 3),
        "observed_recovery_ms": round(recovery_ms, 3),
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dsn", required=True)
    parser.add_argument("--report", type=Path, required=True)
    args = parser.parse_args()
    try:
        report = _run(args.dsn)
        args.report.write_text(
            json.dumps(report, sort_keys=True, indent=2) + "\n",
            encoding="utf-8",
        )
        print(
            "RECOVERY_DRILL_VERIFY=PASS "
            f"events={report['durable_event_count']} "
            f"recovery_ms={report['observed_recovery_ms']}"
        )
    finally:
        _delete_namespace(args.dsn)


if __name__ == "__main__":
    main()
