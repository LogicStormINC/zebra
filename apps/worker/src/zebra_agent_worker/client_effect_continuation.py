"""Waiting-for-client-effect restore gate (mirror of waiting_children)."""

from __future__ import annotations

from typing import Any

from agent_core.domain.events import EventActor, EventType, SessionEvent


def is_waiting_client_effect_suspension(events: list[SessionEvent]) -> bool:
    """True when the stream's live epoch waits on a browser effect."""

    waiting = False
    for event in events:
        if event.event_type is EventType.SESSION_WAITING_FOR_CLIENT_EFFECT:
            waiting = True
        if event.event_type in (
            EventType.SESSION_RESUMED,
            EventType.SESSION_COMPLETED,
            EventType.SESSION_FAILED,
            EventType.SESSION_CANCELLED,
        ):
            waiting = False
    return waiting


def has_trusted_client_effect_resume(events: list[SessionEvent]) -> bool:
    """Only a HARNESS resume command with a client effect result counts."""

    for event in events:
        if (
            event.event_type is EventType.SESSION_COMMAND_ACCEPTED
            and event.actor is EventActor.HARNESS
            and event.payload.get("kind") == "resume"
            and isinstance(event.payload.get("payload"), dict)
            and "client_effect_result" in event.payload["payload"]
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
