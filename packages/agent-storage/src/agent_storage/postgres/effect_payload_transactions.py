"""Caller-owned PostgreSQL transactions for Effect and Artifact linkage."""

from typing import Any
from uuid import uuid4

from agent_core.domain.cloud_artifact_requests import ArtifactFinalizeRequest
from agent_core.domain.effect_dispatch import (
    EffectClaim,
    EffectDispatch,
    EffectDispatchStateError,
    EffectDispatchStatus,
    EffectEvidence,
    EffectScheduleRequest,
)
from agent_core.domain.events import SessionEvent
from agent_core.domain.tools import ToolResult
from agent_core.ports.aggregate_mutation import WorkerMutationAuthority
from psycopg.types.json import Jsonb

from agent_storage.postgres.artifact_payload_transaction_support import (
    assert_worker_boundary,
)
from agent_storage.postgres.artifact_payload_worker_transitions import (
    finalize_after_boundary,
)
from agent_storage.postgres.effects import (
    assert_terminal_event,
    effect_dispatch_from_row,
    find_initial_dispatch,
    lock_dispatch,
    require_same_claim,
    same_schedule,
    write_terminal,
)
from agent_storage.postgres.events import append_event_in_transaction
from agent_storage.postgres.leases import assert_current_lease_fence


def schedule_effect_in_transaction(
    connection: Any,
    namespace: str,
    request: EffectScheduleRequest,
) -> EffectDispatch:
    existing = find_initial_dispatch(
        connection,
        namespace,
        request.root_session_id,
        request.ledger_key,
    )
    if existing is not None:
        return same_schedule(existing, request)
    append_event_in_transaction(connection, namespace, request.started_event)
    return _insert_initial_dispatch(connection, namespace, request)


def schedule_effect_with_payload_in_transaction(
    connection: Any,
    namespace: str,
    request: EffectScheduleRequest,
    authority: WorkerMutationAuthority,
    artifact_finalize: ArtifactFinalizeRequest,
) -> EffectDispatch:
    assert_worker_boundary(connection, namespace, request.execution_session_id, authority)
    existing = find_initial_dispatch(
        connection,
        namespace,
        request.root_session_id,
        request.ledger_key,
    )
    if existing is not None:
        # ACK-loss retries may carry a freshly allocated Event identity. The durable
        # Effect identity and exact Artifact reference are the replay authority.
        return same_schedule(existing, request)
    _require_event_binding(request.started_event, artifact_finalize)
    if request.payload_artifact_ref != artifact_finalize.event_binding.artifact_uri:
        raise EffectDispatchStateError("Effect intent references another Artifact")
    append_event_in_transaction(connection, namespace, request.started_event)
    finalize_after_boundary(connection, namespace, artifact_finalize)
    return _insert_initial_dispatch(connection, namespace, request)


def finish_claim_in_transaction(
    connection: Any,
    namespace: str,
    claim: EffectClaim,
    *,
    status: EffectDispatchStatus,
    terminal_event: SessionEvent,
    result: ToolResult | None = None,
    evidence: EffectEvidence | None = None,
) -> SessionEvent:
    assert_terminal_event(claim.dispatch, status, terminal_event)
    assert_current_lease_fence(
        connection,
        namespace,
        claim.dispatch.execution_session_id,
        claim.claim_fence,
    )
    row = lock_dispatch(connection, namespace, claim.dispatch.dispatch_id)
    require_same_claim(row, claim)
    _require_active_claim(connection, claim)
    append_event_in_transaction(connection, namespace, terminal_event)
    write_terminal(
        connection,
        namespace,
        claim.dispatch.dispatch_id,
        status=status,
        terminal_event=terminal_event,
        result=result,
        evidence=evidence,
    )
    return terminal_event


def finish_claim_with_payload_in_transaction(
    connection: Any,
    namespace: str,
    claim: EffectClaim,
    *,
    status: EffectDispatchStatus,
    terminal_event: SessionEvent,
    authority: WorkerMutationAuthority,
    artifact_finalize: ArtifactFinalizeRequest,
    result: ToolResult | None = None,
    evidence: EffectEvidence | None = None,
) -> SessionEvent:
    assert_terminal_event(claim.dispatch, status, terminal_event)
    if (
        authority.deployment_namespace != namespace
        or authority.session_id != terminal_event.session_id
    ):
        raise EffectDispatchStateError("Effect payload authority has the wrong scope")
    assert_current_lease_fence(
        connection,
        namespace,
        claim.dispatch.execution_session_id,
        authority.lease_fence,
    )
    if authority.lease_fence != claim.claim_fence:
        raise EffectDispatchStateError("Effect payload authority does not own the claim")
    row = lock_dispatch(connection, namespace, claim.dispatch.dispatch_id)
    require_same_claim(row, claim)
    _require_active_claim(connection, claim)
    # Lock the Effect claim before the stream to preserve the existing terminal
    # transition lock order; the payload row is locked only after Event append.
    assert_worker_boundary(connection, namespace, terminal_event.session_id, authority)
    _require_event_binding(terminal_event, artifact_finalize)
    append_event_in_transaction(connection, namespace, terminal_event)
    finalize_after_boundary(connection, namespace, artifact_finalize)
    write_terminal(
        connection,
        namespace,
        claim.dispatch.dispatch_id,
        status=status,
        terminal_event=terminal_event,
        result=result,
        evidence=evidence,
    )
    return terminal_event


def _insert_initial_dispatch(
    connection: Any,
    namespace: str,
    request: EffectScheduleRequest,
) -> EffectDispatch:
    row = connection.execute(
        """
        INSERT INTO effect_outbox (
            deployment_namespace, dispatch_id, execution_session_id,
            root_session_id, ledger_key, attempt, request_hash,
            effect_identity, payload_artifact_ref, status, intent_event_id
        ) VALUES (%s, %s, %s, %s, %s, 1, %s, %s, %s, 'pending', %s)
        RETURNING *
        """,
        (
            namespace,
            uuid4(),
            request.execution_session_id,
            request.root_session_id,
            request.ledger_key,
            request.request_hash,
            Jsonb(request.identity.model_dump(mode="json")),
            request.payload_artifact_ref,
            request.started_event.event_id,
        ),
    ).fetchone()
    assert row is not None
    return effect_dispatch_from_row(row)


def _require_event_binding(
    event: SessionEvent,
    artifact_finalize: ArtifactFinalizeRequest,
) -> None:
    binding = artifact_finalize.event_binding
    if (
        artifact_finalize.session_id != event.session_id
        or binding.event_id != event.event_id
        or binding.sequence != event.sequence
    ):
        raise EffectDispatchStateError("Artifact finalize does not bind the Effect Event")


def _require_active_claim(connection: Any, claim: EffectClaim) -> None:
    active = connection.execute(
        "SELECT %s::timestamptz > transaction_timestamp() AS is_active",
        (claim.claim_expires_at,),
    ).fetchone()
    assert active is not None
    if not active["is_active"]:
        raise EffectDispatchStateError("effect claim has expired")
