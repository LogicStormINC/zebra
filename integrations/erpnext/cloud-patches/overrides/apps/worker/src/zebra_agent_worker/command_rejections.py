"""Permanent legacy validation outcomes in the existing idempotency receipt store."""

from datetime import UTC, datetime
from hashlib import sha256
from typing import Literal

from agent_core.application import current_turn
from agent_core.contracts.session_commands import validate_accepted_session_command
from agent_core.domain.events import EventActor, EventType, SessionEvent
from agent_core.ports.event_store import EventStorePort
from agent_core.ports.idempotency_store import IdempotencyRecord, IdempotencyStorePort
from agent_storage.postgres.legacy_command_candidates import LEGACY_REJECTION_ACTION


def command_rejected(store: IdempotencyStorePort, event: SessionEvent) -> bool:
    receipt = store.get(action=LEGACY_REJECTION_ACTION, idempotency_key=str(event.event_id))
    if receipt is None:
        return False
    if receipt.request_hash != _fingerprint(event):
        raise ValueError("legacy rejection receipt conflicts with canonical command")
    return True


def reject_command(
    store: IdempotencyStorePort,
    event: SessionEvent,
    reason: Literal[
        "invalid_command",
        "unsupported_control",
        "legacy_observation_only",
        "private_workspace_not_activated",
    ],
) -> None:
    store.save(
        IdempotencyRecord(
            action=LEGACY_REJECTION_ACTION,
            idempotency_key=str(event.event_id),
            request_hash=_fingerprint(event),
            status_code=(
                422
                if reason == "invalid_command"
                else 501
                if reason == "unsupported_control"
                else 409
            ),
            response_body={
                "status": "rejected",
                "reason": reason,
                "accepted_event_id": str(event.event_id),
                "session_id": str(event.session_id),
            },
            created_at=datetime.now(UTC),
        )
    )


def _fingerprint(event: SessionEvent) -> str:
    return sha256(event.model_dump_json().encode()).hexdigest()


def fail_rejected_continuation(store: EventStorePort, command: SessionEvent) -> None:
    """An invalid internal resume must not leave its live browser wait hanging."""
    if command.actor is not EventActor.HARNESS or command.payload.get("kind") != "resume":
        return
    events = store.list_for_session(command.session_id)
    boundaries = [
        e
        for e in events
        if e.event_type
        in {
            EventType.SESSION_WAITING_FOR_CLIENT_EFFECT,
            EventType.SESSION_RESUMED,
            EventType.SESSION_COMPLETED,
            EventType.SESSION_FAILED,
            EventType.SESSION_CANCELLED,
        }
    ]
    if (
        not boundaries
        or boundaries[-1].event_type is not EventType.SESSION_WAITING_FOR_CLIENT_EFFECT
    ):
        return
    body = command.payload.get("payload")
    result = body.get("client_effect_result") if isinstance(body, dict) else None
    if not isinstance(result, dict) or result.get("client_effect_id") not in boundaries[
        -1
    ].payload.get("client_effect_ids", []):
        return
    for event in events:
        if (
            event.sequence <= command.sequence
            or event.event_type is not EventType.SESSION_COMMAND_ACCEPTED
        ):
            continue
        if event.payload.get("kind") in {"stop", "cancel", "suspend"}:
            return
        if event.actor is not EventActor.HARNESS or event.payload.get("payload") != body:
            continue
        try:
            validate_accepted_session_command(
                event.payload,
                session_id=event.session_id,
                idempotency_key=event.idempotency_key,
            )
        except ValueError:
            continue
        return  # A reconciled canonical continuation already supersedes this legacy event.
    metadata = {"stop_reason": "resume_command_rejected", "command_event_id": str(command.event_id)}
    summary = "The browser action returned, but its continuation could not be accepted."
    turn = current_turn(events)
    payloads: list[tuple[EventType, dict[str, object]]] = []
    if turn is not None:
        payloads.append(
            (
                EventType.TURN_FAILED,
                {
                    "turn_id": turn.turn_id,
                    "turn_index": turn.turn_index,
                    "reason": summary,
                    "closes_segment": True,
                    "attempt_number": 1,
                    "metadata": metadata,
                },
            )
        )
    payloads.append(
        (
            EventType.SESSION_FAILED,
            {
                "attempt_number": 1,
                "summary": summary,
                "metadata": metadata,
            },
        )
    )
    for offset, (kind, payload) in enumerate(payloads, 1):
        store.append(
            SessionEvent.create(
                session_id=command.session_id,
                sequence=events[-1].sequence + offset,
                event_type=kind,
                actor=EventActor.HARNESS,
                payload=payload,
                created_at=datetime.now(UTC),
                idempotency_key=f"rejected-continuation:{command.event_id}:{kind.value}",
            )
        )
