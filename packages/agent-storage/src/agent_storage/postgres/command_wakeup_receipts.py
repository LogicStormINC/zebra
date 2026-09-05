"""Attribute definite canonical worker boundaries to one exact command LeaseFence."""

from typing import Any

from agent_core.contracts.turn_events import validate_turn_identity
from agent_core.domain.events import EventType, SessionEvent
from agent_core.ports.aggregate_mutation import WorkerMutationAuthority

HANDLED_EVENTS = frozenset({
    EventType.APPROVAL_REQUESTED, EventType.CLARIFICATION_REQUESTED,
    EventType.SESSION_WAITING_FOR_CLIENT_EFFECT, EventType.SESSION_SUSPENDED,
    EventType.TURN_COMPLETED, EventType.TURN_FAILED, EventType.TURN_CANCELLED,
    EventType.SESSION_COMPLETED, EventType.SESSION_FAILED, EventType.SESSION_CANCELLED,
})


def record_worker_command_boundary(
    connection: Any, event: SessionEvent, authority: WorkerMutationAuthority,
) -> None:
    """Caller already holds the current lease and committed canonical projections.

    The primary commit is atomic. Invocation by project_persisted_worker_event is
    exact reconciliation only: it cannot retroactively make a companion's earlier
    Event transaction atomic. Unassociated legacy workers remain unchanged.
    """
    if event.event_type not in HANDLED_EVENTS | {EventType.HARNESS_ATTEMPT_STARTED}:
        return
    if event.session_id != authority.session_id:
        raise ValueError("worker command boundary session mismatch")
    fence = authority.lease_fence
    row = connection.execute(
        """SELECT receipt.*, accepted.sequence AS accepted_sequence,
                  pending.origin, started.sequence AS started_sequence
           FROM command_handoff_receipts AS receipt
           JOIN session_events AS accepted
             ON accepted.deployment_namespace = receipt.deployment_namespace
            AND accepted.event_id = receipt.accepted_event_id
            AND accepted.session_id = receipt.session_id
            AND accepted.event_type = 'session_command_accepted'
           JOIN session_command_pending AS pending
             ON pending.deployment_namespace = receipt.deployment_namespace
            AND pending.accepted_event_id = receipt.accepted_event_id
            AND pending.session_id = receipt.session_id
            AND pending.scope_key = receipt.scope_key AND pending.command_id = receipt.command_id
           LEFT JOIN session_events AS started
             ON started.deployment_namespace = receipt.deployment_namespace
            AND started.event_id = receipt.started_event_id
            AND started.session_id = receipt.session_id
            AND started.event_type = 'harness_attempt_started'
           WHERE receipt.deployment_namespace = %s AND receipt.session_id = %s
             AND receipt.status = 'accepted' AND receipt.control_plane_epoch = %s
             AND receipt.fencing_token = %s AND receipt.owner_instance_id = %s
           FOR UPDATE OF receipt""",
        (authority.deployment_namespace, event.session_id, fence.control_plane_epoch,
         fence.fencing_token, fence.owner_instance_id),
    ).fetchone()
    if row is None or row["origin"] != "live" or row["execution_floor_sequence"] is None:
        return
    # Never infer attribution from a later Event under a different fence, or
    # replay an old worker's Event already present when this handoff acquired.
    if event.sequence <= max(row["accepted_sequence"], row["execution_floor_sequence"]):
        return
    canonical = connection.execute(
        """SELECT event_id, session_id, sequence, event_type, payload, actor,
                  created_at, causation_id, correlation_id, idempotency_key,
                  policy_version, model_profile FROM session_events
           WHERE deployment_namespace = %s AND event_id = %s""",
        (authority.deployment_namespace, event.event_id),
    ).fetchone()
    if canonical is None or SessionEvent.model_validate(canonical) != event:
        raise ValueError("worker command boundary requires the exact canonical Event")
    if row["handled_event_id"] is not None:
        return
    if event.event_type is EventType.HARNESS_ATTEMPT_STARTED:
        if row["started_event_id"] is None:
            connection.execute(
                """UPDATE command_handoff_receipts SET started_event_id = %s
                   WHERE deployment_namespace = %s AND accepted_event_id = %s""",
                (event.event_id, authority.deployment_namespace, row["accepted_event_id"]),
            )
        return
    if (row["started_sequence"] is None or event.sequence <= row["started_sequence"]
            or row["started_sequence"] <= max(
                row["accepted_sequence"], row["execution_floor_sequence"]
            )):
        return
    turn_id = event.payload.get("turn_id")
    if turn_id is not None:
        try:
            if not isinstance(turn_id, str):
                raise ValueError("invalid turn ID")
            turn_id = validate_turn_identity(turn_id)
        except ValueError:
            raise ValueError("invalid canonical boundary turn ID") from None
    connection.execute(
        """UPDATE command_handoff_receipts SET handled_event_id = %s, turn_id = %s
           WHERE deployment_namespace = %s AND accepted_event_id = %s""",
        (event.event_id, turn_id, authority.deployment_namespace, row["accepted_event_id"]),
    )
    connection.execute(
        """UPDATE session_command_pending SET status = 'done'
           WHERE deployment_namespace = %s AND accepted_event_id = %s AND status = 'pending'""",
        (authority.deployment_namespace, row["accepted_event_id"]),
    )
