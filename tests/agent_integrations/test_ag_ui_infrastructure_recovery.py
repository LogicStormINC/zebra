"""Same native Run/Turn suspension semantics for every business adapter."""

import pytest
from ag_ui.core import RunErrorEvent, RunFinishedEvent, StateSnapshotEvent
from agent_core.domain.events import EventActor, EventType
from agent_core.domain.turns import derive_turn_id
from agent_integrations.ag_ui.contracts import AgUiProjectionError, AgUiRunIdentity
from agent_integrations.ag_ui.projection import AgUiProjector
from agent_integrations.ag_ui.projection_state import ProjectionState

from tests.agent_integrations.test_ag_ui_turn_projection import _identity, _stream

REASONS = [
    "execution_storage_contention",
    "execution_storage_unavailable",
    "execution_authority_unavailable",
]


@pytest.mark.parametrize("reason", REASONS)
def test_long_history_reconnect_retains_completed_turns_and_pauses_current_only(reason):
    events, add = _stream()
    # Many completed Turns followed by a distinct current Turn. Projection alone
    # cannot run a model/tool or change source facts.
    for index in range(120):
        add(
            EventType.USER_MESSAGE_RECEIVED,
            {
                "content": "request",
                "turn_id": str(derive_turn_id(events[0].session_id, index)),
                "turn_index": index,
            },
            actor=EventActor.USER,
        )
        add(
            EventType.MODEL_RESPONSE_RECEIVED,
            {"model_call_id": f"model-{index}", "assistant_message": f"answer-{index}"},
        )
        add(
            EventType.TURN_COMPLETED,
            {
                "turn_id": str(derive_turn_id(events[0].session_id, index)),
                "turn_index": index,
                "closes_segment": False,
            },
        )
    identity = _identity(events)
    projector = AgUiProjector()
    cursor = projector.project(events, identity).next_cursor
    add(
        EventType.USER_MESSAGE_RECEIVED,
        {
            "content": "next request",
            "turn_id": str(derive_turn_id(events[0].session_id, 120)),
            "turn_index": 120,
        },
        actor=EventActor.USER,
    )
    add(EventType.SESSION_SUSPENDED, {"reason": reason, "metadata": {"retryable": False}})
    source = tuple(events)
    tail = projector.project(events, identity, after=cursor)
    full = projector.project(events, identity)
    assert tuple(events) == source
    assert not any(isinstance(e, RunErrorEvent) for e in tail.events)
    (finish,) = [e for e in tail.events if isinstance(e, RunFinishedEvent)]
    assert finish.run_id == identity.run_id and finish.outcome.type == "interrupt"
    assert finish.outcome.interrupts[0].reason == reason
    (state,) = [e for e in tail.events if isinstance(e, StateSnapshotEvent)]
    assert state.snapshot["session"] == {
        "status": "suspended",
        "reason": reason,
        "retryable": False,
    }
    assert (
        sum(isinstance(e, RunFinishedEvent) and e.outcome.type == "success" for e in full.events)
        == 120
    )
    assert projector.project(events, identity, after=tail.next_cursor).events == ()
    incremental = ProjectionState()
    for event in events:
        tuple(projector.project_events([event], identity, state=incremental))
    assert incremental.turn_finished
    other = AgUiRunIdentity(session_id=identity.session_id, thread_id="other", run_id="other")
    with pytest.raises(AgUiProjectionError, match="another Session/run"):
        incremental.bind(other)


def test_completed_turn_is_not_reversed_by_trailing_infrastructure_suspension():
    events, add = _stream()
    add(
        EventType.TURN_COMPLETED,
        {
            "turn_id": str(derive_turn_id(events[0].session_id, 0)),
            "turn_index": 0,
            "closes_segment": False,
        },
    )
    add(EventType.SESSION_SUSPENDED, {"reason": REASONS[0]})
    frames = AgUiProjector().project(events, _identity(events)).events
    assert not any(isinstance(e, RunErrorEvent) for e in frames)
    assert [e.outcome.type for e in frames if isinstance(e, RunFinishedEvent)] == ["success"]
