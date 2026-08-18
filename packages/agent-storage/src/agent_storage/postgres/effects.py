"""Shared row and transition primitives for the PostgreSQL Effect aggregate."""

from datetime import timedelta
from typing import Any, cast
from uuid import UUID

from agent_core.domain.effect_dispatch import (
    EffectClaim,
    EffectDispatch,
    EffectDispatchConflictError,
    EffectDispatchStateError,
    EffectDispatchStatus,
    EffectEvidence,
    EffectScheduleRequest,
)
from agent_core.domain.events import EventType, SessionEvent
from agent_core.domain.leases import LeaseFence
from agent_core.domain.session_handoff import EffectIdentity
from agent_core.domain.tools import ToolResult
from psycopg.types.json import Jsonb

from agent_storage.event_rows import ensure_idempotent_event_retry
from agent_storage.postgres.events import read_event_in_transaction


def effect_dispatch_from_row(row: dict[str, Any]) -> EffectDispatch:
    return EffectDispatch(
        dispatch_id=UUID(str(row["dispatch_id"])),
        execution_session_id=row["execution_session_id"],
        root_session_id=row["root_session_id"],
        identity=EffectIdentity.model_validate(row["effect_identity"]),
        attempt=row["attempt"],
        request_hash=row["request_hash"],
        payload_artifact_ref=row["payload_artifact_ref"],
        status=row["status"],
        intent_event_id=row["intent_event_id"],
        terminal_event_id=row["terminal_event_id"],
        result=(None if row["result"] is None else ToolResult.model_validate(row["result"])),
        evidence=(
            None if row["evidence"] is None else EffectEvidence.model_validate(row["evidence"])
        ),
        evidence_history=tuple(
            EffectEvidence.model_validate(item) for item in row["evidence_history"]
        ),
        created_at=row["created_at"],
        updated_at=row["updated_at"],
    )


def effect_claim_from_row(row: dict[str, Any]) -> EffectClaim:
    dispatch = effect_dispatch_from_row(row)
    if any(
        row[field] is None
        for field in (
            "claim_epoch",
            "claim_fencing_token",
            "claim_owner_instance_id",
            "claim_expires_at",
        )
    ):
        raise EffectDispatchStateError("claimed dispatch has incomplete claim identity")
    return EffectClaim(
        dispatch=dispatch,
        claim_fence=LeaseFence(
            control_plane_epoch=UUID(str(row["claim_epoch"])),
            fencing_token=row["claim_fencing_token"],
            owner_instance_id=row["claim_owner_instance_id"],
        ),
        claim_expires_at=row["claim_expires_at"],
    )


def find_initial_dispatch(
    connection: Any,
    deployment_namespace: str,
    root_session_id: UUID,
    ledger_key: str,
    *,
    for_update: bool = False,
) -> EffectDispatch | None:
    suffix = " FOR UPDATE" if for_update else ""
    row = connection.execute(
        """
        SELECT * FROM effect_outbox
        WHERE deployment_namespace = %s AND root_session_id = %s
          AND ledger_key = %s AND attempt = 1
        """
        + suffix,
        (deployment_namespace, root_session_id, ledger_key),
    ).fetchone()
    return None if row is None else effect_dispatch_from_row(row)


def lock_dispatch(
    connection: Any,
    deployment_namespace: str,
    dispatch_id: UUID,
) -> dict[str, Any]:
    row = connection.execute(
        """
        SELECT * FROM effect_outbox
        WHERE deployment_namespace = %s AND dispatch_id = %s
        FOR UPDATE
        """,
        (deployment_namespace, dispatch_id),
    ).fetchone()
    if row is None:
        raise EffectDispatchStateError("effect dispatch does not exist")
    return cast(dict[str, Any], row)


def read_dispatch(
    connection: Any,
    deployment_namespace: str,
    dispatch_id: UUID,
) -> EffectDispatch:
    row = connection.execute(
        """
        SELECT * FROM effect_outbox
        WHERE deployment_namespace = %s AND dispatch_id = %s
        """,
        (deployment_namespace, dispatch_id),
    ).fetchone()
    if row is None:
        raise EffectDispatchStateError("effect dispatch does not exist")
    return effect_dispatch_from_row(row)


def lock_latest_dispatch(
    connection: Any,
    deployment_namespace: str,
    root_session_id: UUID,
    ledger_key: str,
) -> EffectDispatch:
    row = connection.execute(
        """
        SELECT * FROM effect_outbox
        WHERE deployment_namespace = %s AND root_session_id = %s AND ledger_key = %s
        ORDER BY attempt DESC
        LIMIT 1 FOR UPDATE
        """,
        (deployment_namespace, root_session_id, ledger_key),
    ).fetchone()
    if row is None:
        raise EffectDispatchStateError("effect ledger does not exist")
    return effect_dispatch_from_row(row)


def write_terminal(
    connection: Any,
    deployment_namespace: str,
    dispatch_id: UUID,
    *,
    status: EffectDispatchStatus,
    terminal_event: SessionEvent,
    result: ToolResult | None = None,
    evidence: EffectEvidence | None = None,
) -> None:
    connection.execute(
        """
        UPDATE effect_outbox SET status = %s, terminal_event_id = %s,
            result = %s, evidence = %s,
            evidence_history = evidence_history || %s,
            claim_epoch = NULL,
            claim_fencing_token = NULL, claim_owner_instance_id = NULL,
            claim_expires_at = NULL, updated_at = transaction_timestamp()
        WHERE deployment_namespace = %s AND dispatch_id = %s
        """,
        (
            status.value,
            terminal_event.event_id,
            None if result is None else Jsonb(result.model_dump(mode="json")),
            None if evidence is None else Jsonb(evidence.model_dump(mode="json")),
            Jsonb([] if evidence is None else [evidence.model_dump(mode="json")]),
            deployment_namespace,
            dispatch_id,
        ),
    )


def require_same_claim(row: dict[str, Any], claim: EffectClaim) -> None:
    if effect_claim_from_row(row) != claim:
        raise EffectDispatchStateError("effect claim identity is stale")


def assert_terminal_event(
    dispatch: EffectDispatch,
    status: EffectDispatchStatus,
    event: SessionEvent,
) -> None:
    expected = (
        EventType.TOOL_EXECUTION_COMPLETED
        if status is EffectDispatchStatus.SUCCEEDED
        else EventType.TOOL_EXECUTION_FAILED
    )
    require_event(event, expected)
    if event.session_id != dispatch.execution_session_id:
        raise EffectDispatchStateError("terminal Event belongs to another Session")


def positive_ttl(value: timedelta) -> timedelta:
    if value <= timedelta(0):
        raise ValueError("claim ttl must be positive")
    return value


def required_text(value: str, field: str) -> str:
    value = value.strip()
    if not value:
        raise ValueError(f"{field} must not be blank")
    return value


def require_event(event: SessionEvent, expected: EventType) -> None:
    if event.event_type is not expected:
        raise EffectDispatchStateError(f"Event must be {expected.value}")


def same_schedule(
    existing: EffectDispatch,
    request: EffectScheduleRequest,
) -> EffectDispatch:
    if (
        existing.identity != request.identity
        or existing.request_hash != request.request_hash
        or existing.payload_artifact_ref != request.payload_artifact_ref
    ):
        raise EffectDispatchConflictError("effect ledger identity has conflicting meaning")
    return existing


def find_retry(
    connection: Any,
    deployment_namespace: str,
    source: EffectDispatch,
    retry_key: str,
) -> EffectDispatch | None:
    row = connection.execute(
        """
        SELECT * FROM effect_outbox
        WHERE deployment_namespace = %s AND root_session_id = %s
          AND ledger_key = %s AND retry_key = %s
        """,
        (
            deployment_namespace,
            source.root_session_id,
            source.ledger_key,
            retry_key,
        ),
    ).fetchone()
    return None if row is None else effect_dispatch_from_row(row)


def same_retry(
    connection: Any,
    deployment_namespace: str,
    existing: EffectDispatch,
    source: EffectDispatch,
    started_event: SessionEvent,
) -> EffectDispatch:
    same_meaning = (
        existing.root_session_id == source.root_session_id
        and existing.identity == source.identity
        and existing.request_hash == source.request_hash
        and existing.attempt == source.attempt + 1
        and existing.execution_session_id == started_event.session_id
    )
    if not same_meaning:
        raise EffectDispatchConflictError("retry key has conflicting meaning")
    persisted_event = read_event_in_transaction(
        connection,
        deployment_namespace,
        existing.intent_event_id,
    )
    if persisted_event is None:
        raise EffectDispatchStateError("retry intent Event is missing")
    try:
        ensure_idempotent_event_retry(persisted_event, started_event)
    except ValueError as exc:
        raise EffectDispatchConflictError("retry key has conflicting meaning") from exc
    return existing
