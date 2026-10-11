"""Compact Turn count is the full canonical oracle, not retained length or last index."""

from agent_core.application.task_turn_fields import SegmentTurnReadState
from agent_core.application.turn_projection import current_turn, project_turns
from agent_core.domain.events import EventActor, EventType
from agent_storage.task_read_summary_rows import turn_state

from tests.agent_core.test_turn_projection import _bootstrap


def test_exact_count_survives_closed_history_duplicate_ids_legacy_and_actor_filters():
    base = _bootstrap()[0]
    events = []
    state = SegmentTurnReadState()
    steps = [
        (EventType.USER_MESSAGE_RECEIVED, EventActor.USER, {"content": "legacy"}),
        (EventType.USER_MESSAGE_RECEIVED, EventActor.USER, {"content": "same legacy"}),
        (EventType.SESSION_COMPLETED, EventActor.HARNESS, {}),
        (EventType.USER_MESSAGE_RECEIVED, EventActor.USER, {"content": "next legacy"}),
        (EventType.TURN_CANCELLED, EventActor.SYSTEM, {"turn_id": "legacy-turn:3"}),
        (
            EventType.USER_MESSAGE_RECEIVED,
            EventActor.USER,
            {"content": "automation", "actor_kind": "automation", "turn_id": "ignored"},
        ),
    ]
    for index in range(50):
        # Reusing a closed Turn ID and nonmonotonic explicit indexes are legal
        # historical oracle inputs; neither is a substitute for exact cardinality.
        steps.extend(
            [
                (
                    EventType.USER_MESSAGE_RECEIVED,
                    EventActor.USER,
                    {"content": "x", "turn_id": "duplicate", "turn_index": index % 3},
                ),
                (EventType.TURN_COMPLETED, EventActor.HARNESS, {"turn_id": "duplicate"}),
            ]
        )
    steps.extend(
        [
            (EventType.USER_MESSAGE_RECEIVED, EventActor.SYSTEM, {"content": "nonhuman"}),
            (
                EventType.USER_MESSAGE_RECEIVED,
                EventActor.USER,
                {"content": "handoff", "origin": "session_handoff"},
            ),
            (
                EventType.USER_MESSAGE_RECEIVED,
                EventActor.USER,
                {"content": "x", "turn_id": "A", "turn_index": 10000},
            ),
            (
                EventType.USER_MESSAGE_RECEIVED,
                EventActor.USER,
                {"content": "x", "turn_id": "A", "turn_index": 0},
            ),
            (EventType.CLARIFICATION_REQUESTED, EventActor.HARNESS, {}),
            (EventType.TURN_FAILED, EventActor.HARNESS, {"turn_id": "A"}),
        ]
    )
    for sequence, (kind, actor, payload) in enumerate(steps):
        event = base.model_copy(
            update={
                "sequence": sequence,
                "event_type": kind,
                "actor": actor,
                "payload": payload,
            }
        )
        events.append(event)
        state = SegmentTurnReadState.model_validate_json(state.advance(event).model_dump_json())
        assert state.human_turn_count == len(project_turns(events))
        assert state.current_turn() == current_turn(events)
    assert state.human_turn_count > len(state.records)


def test_old_turn_checkpoint_is_pending_rebuild_not_an_inferred_zero_count():
    old = {"turn_state": {"version": 2, "through_sequence": 90000, "segments": {}}}
    assert turn_state(old, 90000) == {"version": 3, "through_sequence": -1, "segments": {}}
