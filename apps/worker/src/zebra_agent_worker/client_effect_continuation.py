"""Waiting-for-client-effect restore gate (mirror of waiting_children)."""

from __future__ import annotations

from typing import Any

from agent_core.domain.events import EventActor, EventType, SessionEvent


def is_waiting_client_effect_suspension(events: list[SessionEvent]) -> bool:
    """True when the live epoch has an unresolved browser-effect continuation.

    ``CLIENT_EFFECT_SCHEDULED`` is deliberately sufficient here.  A fast
    browser can return its receipt before finalization appends
    ``SESSION_WAITING_FOR_CLIENT_EFFECT``; recovery must close that race rather
    than strand the already accepted receipt.
    """

    return bool(pending_client_effect_ids(events))


def blocks_client_effect_recovery(event: SessionEvent) -> bool:
    """A receipt records an effect result; it cannot override a later control boundary."""
    return event.event_type in {
        EventType.SESSION_SUSPENDED, EventType.SESSION_COMPLETED,
        EventType.SESSION_FAILED, EventType.SESSION_CANCELLED,
        EventType.TURN_COMPLETED, EventType.TURN_FAILED, EventType.TURN_CANCELLED,
        EventType.USER_MESSAGE_RECEIVED, EventType.APPROVAL_REQUESTED,
        EventType.CLARIFICATION_REQUESTED,
    } or (
        event.event_type is EventType.SESSION_COMMAND_ACCEPTED
        and event.payload.get("kind") in {"stop", "cancel", "suspend", "run", "message"}
    )


def pending_client_effect_ids(events: list[SessionEvent]) -> tuple[str, ...]:
    """Return the bounded effect ids belonging to the unresolved live epoch."""

    pending: list[str] = []
    for event in events:
        if event.event_type is EventType.CLIENT_EFFECT_SCHEDULED:
            effect_id = event.payload.get("client_effect_id")
            if isinstance(effect_id, str) and effect_id and effect_id not in pending:
                pending.append(effect_id)
        elif event.event_type is EventType.SESSION_WAITING_FOR_CLIENT_EFFECT:
            effect_ids = event.payload.get("client_effect_ids")
            if isinstance(effect_ids, list):
                pending = [
                    item
                    for item in effect_ids
                    if isinstance(item, str) and item.strip()
                ][:32]
        elif event.event_type is EventType.SESSION_RESUMED or blocks_client_effect_recovery(event):
            pending = []
    return tuple(pending[:32])


def has_trusted_client_effect_resume(events: list[SessionEvent]) -> bool:
    """Only a HARNESS resume command with a client effect result counts."""

    pending = pending_client_effect_ids(events)
    for event in events:
        if (
            event.event_type is EventType.SESSION_COMMAND_ACCEPTED
            and event.actor is EventActor.HARNESS
            and event.payload.get("kind") == "resume"
            and isinstance(event.payload.get("payload"), dict)
            and isinstance(event.payload["payload"].get("client_effect_result"), dict)
            and event.payload["payload"]["client_effect_result"].get("client_effect_id") in pending
        ):
            return True
    return False


def restore_client_effect_wait(
    recorder: Any, events: list[SessionEvent]
) -> bool:
    """Resume gate: waiting + trusted receipt resume -> SESSION_RESUMED."""

    if not is_waiting_client_effect_suspension(events):
        return False
    if not has_trusted_client_effect_resume(events):
        return False
    recorder.append(
        EventType.SESSION_RESUMED,
        EventActor.HARNESS,
        {"reason": "waiting_client_effect_resolved"},
    )
    return True
