from uuid import UUID

import pytest
from agent_core.contracts import SessionCommand, SessionCommandKind
from agent_core.domain.events import EventActor, EventType, SessionEvent
from agent_core.domain.identifiers import SessionId
from agent_core.domain.turns import derive_turn_id
from zebra_agent_api.extension_turn_admission import CloudExtensionTurnAdmission

SESSION_ID = SessionId(UUID("11111111-1111-1111-1111-111111111111"))


def _accepted() -> SessionEvent:
    command = SessionCommand(
        session_id=SESSION_ID,
        kind=SessionCommandKind.MESSAGE,
        expected_revision=0,
        idempotency_key="integrity-command",
        payload={"content": "hello"},
    )
    return SessionEvent.create(
        session_id=SESSION_ID,
        sequence=1,
        event_type=EventType.SESSION_COMMAND_ACCEPTED,
        actor=EventActor.USER,
        payload=command.event_payload(),
        idempotency_key=command.idempotency_key,
    )


def _message(accepted: SessionEvent, *, sequence: int, legacy: bool) -> SessionEvent:
    return SessionEvent.create(
        session_id=SESSION_ID,
        sequence=sequence,
        event_type=EventType.USER_MESSAGE_RECEIVED,
        actor=EventActor.USER,
        payload={
            "content": "hello",
            "turn_id": str(derive_turn_id(SESSION_ID, 0)),
            "turn_index": 0,
            "origin": "human",
        },
        causation_id=None if legacy else accepted.event_id,
        idempotency_key=(
            "integrity-command:message"
            if legacy
            else f"command-input:{accepted.event_id}"
        ),
    )


@pytest.mark.parametrize("corruption", ["canonical_legacy", "two_canonical", "accepted"])
def test_pending_admission_rejects_ambiguous_or_duplicate_history(corruption: str) -> None:
    accepted = _accepted()
    canonical = _message(accepted, sequence=2, legacy=False)
    if corruption == "canonical_legacy":
        events = [accepted, canonical, _message(accepted, sequence=3, legacy=True)]
    elif corruption == "two_canonical":
        events = [accepted, canonical, _message(accepted, sequence=3, legacy=False)]
    else:
        events = [accepted, accepted, canonical]

    with pytest.raises(ValueError, match="materialization integrity check failed"):
        CloudExtensionTurnAdmission._has_pending_message(events)
