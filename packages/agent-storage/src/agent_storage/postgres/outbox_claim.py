"""Existing queue claim and bounded exact claim transactions."""

from datetime import timedelta
from typing import Any

from agent_core.domain.effect_dispatch import (
    EffectClaim,
    EffectDispatch,
    EffectDispatchStatus,
)
from agent_core.domain.identifiers import SessionId
from agent_core.domain.leases import LeaseFence
from agent_core.ports.effect_dispatch import effect_input

from agent_storage.postgres.effects import effect_claim_from_row, effect_dispatch_from_row
from agent_storage.postgres.leases import assert_current_lease_fence


def claim_next_in_transaction(
    connection: Any,
    namespace: str,
    execution_session_id: SessionId,
    fence: LeaseFence,
    ttl: timedelta,
) -> EffectClaim | None:
    assert_current_lease_fence(connection, namespace, execution_session_id, fence)
    row = connection.execute(
        """
        WITH candidate AS (
            SELECT dispatch_id FROM effect_outbox
            WHERE deployment_namespace = %s
              AND execution_session_id = %s AND status = 'pending'
            ORDER BY created_at, dispatch_id
            FOR UPDATE SKIP LOCKED LIMIT 1
        )
        UPDATE effect_outbox AS effect
        SET status = 'claimed', claim_epoch = %s,
            claim_fencing_token = %s, claim_owner_instance_id = %s,
            claim_expires_at = transaction_timestamp() + %s::interval,
            updated_at = transaction_timestamp()
        FROM candidate
        WHERE effect.deployment_namespace = %s
          AND effect.dispatch_id = candidate.dispatch_id
        RETURNING effect.*
        """,
        (namespace, execution_session_id, fence.control_plane_epoch,
         fence.fencing_token, fence.owner_instance_id, ttl, namespace),
    ).fetchone()
    return None if row is None else effect_claim_from_row(row)


def claim_exact_in_transaction(
    connection: Any,
    namespace: str,
    execution_session_id: SessionId,
    expected: EffectDispatch,
    fence: LeaseFence,
    ttl: timedelta,
) -> EffectClaim | None:
    expected = EffectDispatch.model_validate(effect_input(expected), strict=True, extra="forbid")
    fence = LeaseFence.model_validate(effect_input(fence), strict=True, extra="forbid")
    assert_current_lease_fence(connection, namespace, execution_session_id, fence)
    if (
        expected.execution_session_id != execution_session_id
        or expected.status is not EffectDispatchStatus.PENDING
    ):
        return None
    row = connection.execute(
        """SELECT * FROM effect_outbox WHERE deployment_namespace=%s
           AND execution_session_id=%s AND dispatch_id=%s AND status='pending'
           FOR UPDATE SKIP LOCKED""",
        (namespace, execution_session_id, expected.dispatch_id),
    ).fetchone()
    if (
        row is None
        or effect_dispatch_from_row(row) != expected
        or row["ledger_key"] != expected.ledger_key
    ):
        return None
    # Sample lease time again after the candidate lock. Claim expiry is measured
    # from this update, rather than the potentially older transaction start.
    assert_current_lease_fence(connection, namespace, execution_session_id, fence)
    claimed = connection.execute(
        """WITH moment AS (SELECT clock_timestamp() AS now)
           UPDATE effect_outbox SET status='claimed', claim_epoch=%s,
           claim_fencing_token=%s, claim_owner_instance_id=%s,
           claim_expires_at=moment.now + %s::interval,
           updated_at=moment.now FROM moment
           WHERE deployment_namespace=%s AND execution_session_id=%s
             AND dispatch_id=%s AND status='pending' RETURNING *""",
        (fence.control_plane_epoch, fence.fencing_token, fence.owner_instance_id,
         ttl, namespace, execution_session_id, expected.dispatch_id),
    ).fetchone()
    return None if claimed is None else effect_claim_from_row(claimed)
