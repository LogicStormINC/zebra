"""Rejected internal continuations terminate visibly unless already repaired."""

import pytest
from agent_core.contracts.session_commands import SessionCommand
from agent_core.domain.events import EventActor, EventType, SessionEvent
from zebra_agent_worker.command_rejections import fail_rejected_continuation

from tests.worker.test_command_consumer import _seed_session


@pytest.mark.parametrize("replacement", [False, True])
def test_invalid_resume_terminates_once_or_yields_to_repair(tmp_path, replacement):
    stores, session_id, revision = _seed_session(tmp_path)
    stores.events.append(
        SessionEvent.create(
            session_id=session_id,
            sequence=revision + 1,
            event_type=EventType.SESSION_WAITING_FOR_CLIENT_EFFECT,
            actor=EventActor.HARNESS,
            payload={"reason": "waiting_client_effect", "client_effect_ids": ["effect-1"]},
        )
    )
    command = SessionCommand(
        session_id=session_id,
        kind="resume",
        expected_revision=revision + 1,
        idempotency_key="bad-resume",
        payload={"client_effect_result": {"client_effect_id": "effect-1"}},
    )
    payload = command.event_payload()
    payload["fingerprint"] = "a" * 64
    event = SessionEvent.create(
        session_id=session_id,
        sequence=revision + 2,
        event_type=EventType.SESSION_COMMAND_ACCEPTED,
        actor=EventActor.HARNESS,
        payload=payload,
        idempotency_key=command.idempotency_key,
    )
    stores.events.append(event)
    if replacement:
        repaired = command.model_copy(update={"idempotency_key": "repaired"})
        stores.events.append(
            SessionEvent.create(
                session_id=session_id,
                sequence=revision + 3,
                event_type=EventType.SESSION_COMMAND_ACCEPTED,
                actor=EventActor.HARNESS,
                payload=repaired.event_payload(),
                idempotency_key=repaired.idempotency_key,
            )
        )
    fail_rejected_continuation(stores.events, event)
    after = stores.events.list_for_session(session_id)
    assert (after[-1].event_type is EventType.SESSION_FAILED) is (not replacement)
    fail_rejected_continuation(stores.events, event)
    assert stores.events.list_for_session(session_id) == after
