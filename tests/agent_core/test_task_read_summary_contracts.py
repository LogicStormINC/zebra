"""Persisted-prefix contracts and incremental public usage match the old oracle."""

import pytest
from agent_core.application.task_model_usage import advance_model_usage, public_model_usage
from agent_core.application.task_turn_fields import SegmentTurnReadState
from agent_core.application.turn_projection import current_turn, project_turns
from agent_core.domain.events import EventActor, EventType, SessionEvent
from agent_core.domain.identifiers import SessionId, TaskId, new_task_id
from agent_core.ports.agent_tasks import TaskEvent
from agent_core.ports.task_read_summaries import TaskAttachmentPage, TaskReadSummary
from zebra_agent_api.task_model_usage import summarize_task_model_usage


@pytest.mark.parametrize("coordinate", [True, -2, 2**63, "1"])
def test_summary_rejects_invalid_source_coordinate(coordinate):
    with pytest.raises(ValueError):
        TaskReadSummary(new_task_id(), coordinate, 9, None, 0, 0)


def test_summary_frontier_and_attachment_empty_window_are_exact():
    task = new_task_id()
    assert TaskReadSummary(task, -1, -1, None, 0, 0).complete
    assert not TaskReadSummary(task, 0, 1, None, 0, 0).complete
    with pytest.raises(ValueError):
        TaskReadSummary(task, 2, 1, None, 0, 0)
    page = TaskAttachmentPage(task, -1, -1, 0, 0, (), 0)
    assert not page.has_more and page.next_ordinal == -1
    with pytest.raises(ValueError, match="omits"):
        TaskAttachmentPage(task, 1, -1, 1, 1, (), 0)


@pytest.mark.parametrize("value", [None, True, False, -1, 0, 1, 1.5, "  high  ", "", {}, []])
def test_incremental_latest_and_cache_semantics_preserve_oracle(value):
    task = new_task_id()
    payloads = [
        {
            "input_tokens": 7,
            "input_token_limit": 100,
            "resolved_model": "old",
            "reasoning_effort": "high",
            "prompt_cache_hit_tokens": 3,
            "token_breakdown": {"messages": 4, "system": 2},
        },
        {
            "input_tokens": value,
            "input_token_limit": value,
            "resolved_model": value,
            "reasoning_effort": value,
            "prompt_cache_hit_tokens": value,
            "prompt_cache_miss_tokens": value,
            "token_breakdown": value,
            "provider": "private",
            "stable_prefix_hash": "private",
        },
    ]
    state = {}
    events = []
    for sequence, payload in enumerate(payloads):
        state = advance_model_usage(state, payload)
        event = SessionEvent.create(
            session_id=SessionId(task),
            sequence=sequence,
            actor=EventActor.HARNESS,
            event_type=EventType.MODEL_RESPONSE_RECEIVED,
            payload={},
        ).model_copy(update={"payload": payload})  # Historical raw payload oracle only.
        events.append(TaskEvent(TaskId(task), sequence, event.session_id, sequence, event))
    assert public_model_usage(state) == summarize_task_model_usage(events)
    assert "provider" not in state["latest"] and "stable_prefix_hash" not in state["latest"]


def test_turn_projection_can_continue_without_replaying_the_prefix():
    from tests.agent_core.test_turn_projection import _bootstrap, _event

    events = _bootstrap(interaction_mode="conversation")
    initial = project_turns(events)
    close = _event(
        events,
        EventType.TURN_COMPLETED,
        {"turn_id": initial[-1].turn_id, "turn_index": 0, "closes_segment": False},
    )
    assert project_turns((close,), initial=initial) == project_turns([*events, close])


def test_turn_state_without_lookup_fails_closed_instead_of_guessing():
    from tests.agent_core.test_turn_projection import _bootstrap

    state = SegmentTurnReadState()
    for event in _bootstrap():
        state = state.advance(event)
    raw = state.model_dump(mode="json")
    raw.pop("lookup")
    with pytest.raises(ValueError, match="Turn lookup"):
        SegmentTurnReadState.model_validate(raw).public_fields()


@pytest.mark.parametrize(
    "steps",
    [
        (
            (EventType.USER_MESSAGE_RECEIVED, "A"),
            (EventType.USER_MESSAGE_RECEIVED, "A"),
            (EventType.SESSION_COMPLETED, ""),
            (EventType.TURN_COMPLETED, "A"),
        ),
        (
            (EventType.USER_MESSAGE_RECEIVED, "A"),
            (EventType.USER_MESSAGE_RECEIVED, "A"),
            (EventType.TURN_COMPLETED, "A"),
            (EventType.USER_MESSAGE_RECEIVED, "B"),
            (EventType.CLARIFICATION_REQUESTED, ""),
            (EventType.TURN_FAILED, "A"),
            (EventType.TURN_COMPLETED, "B"),
        ),
    ],
    ids=["legacy-close-alias", "clarification-alias"],
)
def test_compact_turns_keep_the_actual_duplicate_id_lookup(steps):
    task = new_task_id()
    base = SessionEvent.create(
        session_id=SessionId(task),
        sequence=0,
        actor=EventActor.HARNESS,
        event_type=EventType.MODEL_RESPONSE_RECEIVED,
        payload={},
    )
    events = []
    state = SegmentTurnReadState()
    for sequence, (kind, turn_id) in enumerate(steps):
        # Historical raw payloads are accepted by the canonical projection oracle.
        event = base.model_copy(
            update={
                "sequence": sequence,
                "event_type": kind,
                "actor": EventActor.USER
                if kind is EventType.USER_MESSAGE_RECEIVED
                else EventActor.HARNESS,
                "payload": {"content": "raw", "turn_id": turn_id, "turn_index": sequence},
            }
        )
        events.append(event)
        state = SegmentTurnReadState.model_validate(state.advance(event).model_dump(mode="json"))
        visible = current_turn(events) or project_turns(events)[-1]
        assert state.public_fields()["turn_id"] == visible.turn_id
        assert state.public_fields()["current_turn_status"] == visible.status.value


def test_compact_turns_match_every_randomized_canonical_prefix():
    from random import Random

    rng = Random(4)
    kinds = (
        EventType.USER_MESSAGE_RECEIVED,
        EventType.TURN_COMPLETED,
        EventType.TURN_FAILED,
        EventType.TURN_CANCELLED,
        EventType.APPROVAL_REQUESTED,
        EventType.APPROVAL_GRANTED,
        EventType.CLARIFICATION_REQUESTED,
        EventType.CLARIFICATION_RESPONDED,
        EventType.SESSION_COMPLETED,
    )
    base = SessionEvent.create(
        session_id=SessionId(new_task_id()),
        sequence=0,
        actor=EventActor.HARNESS,
        event_type=EventType.MODEL_RESPONSE_RECEIVED,
        payload={},
    )
    state = SegmentTurnReadState()
    events = []
    for sequence in range(1000):
        kind = rng.choice(kinds)
        event = base.model_copy(
            update={
                "sequence": sequence,
                "event_type": kind,
                "actor": EventActor.USER
                if kind is EventType.USER_MESSAGE_RECEIVED
                else EventActor.HARNESS,
                "payload": {
                    "content": "raw",
                    "turn_id": str(rng.randrange(10)),
                    "turn_index": rng.randrange(10),
                    "closes_segment": False,
                },
            }
        )
        events.append(event)
        state = SegmentTurnReadState.model_validate(state.advance(event).model_dump(mode="json"))
        records = project_turns(events)
        visible = current_turn(events) or (records[-1] if records else None)
        assert state.public_fields() == {
            "interaction_mode": "one_shot",
            "turn_id": visible.turn_id if visible else None,
            "current_turn_status": visible.status.value if visible else None,
        }, sequence
