from __future__ import annotations

from uuid import UUID, uuid4

import pytest
from agent_core.contracts import (
    SessionCommand,
    SessionCommandKind,
    SessionCommandStatus,
    decide_session_command,
)
from agent_core.domain.events import EventActor, EventType, SessionEvent
from agent_core.domain.identifiers import SessionId
from pydantic import ValidationError


def _command(
    kind: SessionCommandKind = SessionCommandKind.RUN,
    *,
    expected_revision: int = 3,
    payload: dict[str, object] | None = None,
) -> SessionCommand:
    return SessionCommand(
        command_id=uuid4(),
        session_id=SessionId(UUID("11111111-1111-1111-1111-111111111111")),
        kind=kind,
        expected_revision=expected_revision,
        idempotency_key="command-1",
        payload={} if payload is None else payload,
    )


def test_command_is_frozen_and_fingerprinted_without_command_id() -> None:
    first = _command()
    second = first.model_copy(update={"command_id": uuid4()})

    assert first.fingerprint == second.fingerprint
    with pytest.raises(ValidationError):
        first.kind = SessionCommandKind.MESSAGE  # type: ignore[misc]


def test_message_and_resume_payloads_are_validated() -> None:
    message = _command(SessionCommandKind.MESSAGE, payload={"content": "hello"})
    resume = _command(
        SessionCommandKind.RESUME,
        payload={"worker_id": "worker-a", "lease_ttl_seconds": 30},
    )

    assert message.payload["content"] == "hello"
    assert resume.payload["worker_id"] == "worker-a"


def test_message_requires_content() -> None:
    with pytest.raises(ValueError, match="payload.content"):
        _command(SessionCommandKind.MESSAGE)


def test_payload_is_bounded_and_json_serializable() -> None:
    with pytest.raises(ValueError, match="JSON serializable"):
        _command(payload={"bad": object()})
    with pytest.raises(ValueError, match="too large"):
        _command(payload={"content": "x" * (64 * 1024)})


def test_accepted_command_has_durable_event_payload() -> None:
    command = _command()
    decision = decide_session_command(command, current_revision=3)

    assert decision.status is SessionCommandStatus.ACCEPTED
    assert decision.event_type is EventType.SESSION_COMMAND_ACCEPTED
    event = SessionEvent.create(
        session_id=command.session_id,
        sequence=4,
        event_type=decision.event_type,
        actor=EventActor.USER,
        payload=command.event_payload(),
        idempotency_key=command.idempotency_key,
    )
    assert event.payload["fingerprint"] == command.fingerprint
    assert event.payload["kind"] == "run"


def test_duplicate_is_returned_before_revision_check() -> None:
    command = _command()
    decision = decide_session_command(
        command,
        current_revision=9,
        existing_fingerprint=command.fingerprint,
    )

    assert decision.status is SessionCommandStatus.DUPLICATE
    assert decision.current_revision == 9


def test_idempotency_reuse_with_different_intent_is_rejected() -> None:
    command = _command()
    changed = command.model_copy(update={"payload": {"prompt": "different"}})

    decision = decide_session_command(
        changed,
        current_revision=3,
        existing_fingerprint=command.fingerprint,
    )

    assert decision.status is SessionCommandStatus.IDEMPOTENCY_CONFLICT


def test_revision_conflict_is_deterministic() -> None:
    decision = decide_session_command(_command(expected_revision=2), current_revision=3)

    assert decision.status is SessionCommandStatus.REVISION_CONFLICT
    assert decision.event_type is None
    assert decision.reason == "expected revision 2, current revision 3"


@pytest.mark.parametrize("corrupted", [True, 1.0, "1"])
def test_expected_revision_rejects_non_integer_coercion(corrupted: object) -> None:
    """A corrupted revision (bool/float/string) must be REJECTED, never
    silently coerced to the integer a fingerprint was computed over —
    the run pre-check trusts these contracts to fail closed."""

    from agent_core.contracts import SessionCommandAcceptedPayload

    command = _command()
    payload = command.event_payload()
    payload["expected_revision"] = corrupted
    with pytest.raises(ValidationError):
        SessionCommandAcceptedPayload.model_validate(payload)
    with pytest.raises(ValidationError):
        SessionCommand(
            command_id=command.command_id,
            session_id=command.session_id,
            kind=command.kind,
            expected_revision=corrupted,  # type: ignore[arg-type]
            idempotency_key=command.idempotency_key,
            payload=dict(command.payload),
        )
