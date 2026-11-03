from unittest.mock import Mock

import pytest
from agent_core.application import current_turn
from agent_core.domain.events import EventActor, EventType, SessionEvent
from agent_core.domain.identifiers import TaskId
from agent_core.domain.sessions import Session
from agent_core.ports.agent_tasks import TaskEvent
from zebra_agent_api.session_message_submission import build_session_message_event
from zebra_agent_api.task_responses import serialize_task_event

from tests.agent_core.test_bundle_definition import removed_model_release_snapshots


def test_follow_up_pins_new_release_and_rejects_removed_explicit_choice():
    old, effective = removed_model_release_snapshots()
    event_store = Mock()
    event_store.list_for_session.return_value = []
    session = Session.create(title="published conversation")
    old_pin = old.bound_version.runtime_assembly.provider_profile.pin
    new_pin = effective.bound_version.runtime_assembly.provider_profile.pin

    alternate_pin = effective.bound_version.runtime_assembly.selectable_profiles[0].pin
    assert alternate_pin != new_pin
    for choice, expected in ((None, new_pin), (alternate_pin.id, alternate_pin)):
        event = build_session_message_event(
            event_store=event_store,
            session=session,
            content="continue",
            clarification_id=None,
            inherited_snapshot=old,
            effective_snapshot=effective,
            selected_model_id=choice,
        )
        assert event.payload["definition_snapshot"] == effective.model_dump(mode="json")
        assert event.payload["selected_model_pin"] == expected.model_dump(mode="json")
        task_event = TaskEvent(
            TaskId(session.session_id), event.sequence, session.session_id, event.sequence, event
        )
        public_payload = serialize_task_event(task_event)["payload"]
        assert public_payload["content"] == "continue"
        assert "definition_snapshot" not in public_payload

    with pytest.raises(ValueError, match="requested model is not selectable"):
        build_session_message_event(
            event_store=event_store,
            session=session,
            content="continue",
            clarification_id=None,
            inherited_snapshot=old,
            effective_snapshot=effective,
            selected_model_id=old_pin.id,
        )


def test_same_session_remembers_explicit_model_until_next_switch():
    _, snapshot = removed_model_release_snapshots()
    assembly = snapshot.bound_version.runtime_assembly
    default = assembly.provider_profile.pin
    alternate = assembly.selectable_profiles[0].pin
    assert default != alternate
    events = []
    event_store = Mock()
    event_store.list_for_session.return_value = events
    session = Session.create(title="model switching")
    pins = []

    for choice in (alternate.id, None, default.id):
        event = build_session_message_event(
            event_store=event_store,
            session=session,
            content="continue",
            clarification_id=None,
            inherited_snapshot=snapshot,
            effective_snapshot=snapshot,
            selected_model_id=choice,
        )
        events.append(event)
        pins.append(event)
        turn = current_turn(events)
        assert turn is not None
        events.append(SessionEvent.create(
            session_id=session.session_id,
            sequence=event.sequence + 1,
            event_type=EventType.TURN_COMPLETED,
            actor=EventActor.HARNESS,
            payload={"turn_id": turn.turn_id, "turn_index": turn.turn_index},
        ))
        session = session.model_copy(update={"current_sequence": events[-1].sequence})

    assert [event.payload["selected_model_pin"] for event in pins] == [
        pin.model_dump(mode="json") for pin in (alternate, alternate, default)
    ]
