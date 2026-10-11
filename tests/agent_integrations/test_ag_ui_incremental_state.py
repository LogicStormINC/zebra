"""Incremental batches retain exact frame identity and reject foreign state."""

from uuid import uuid4

import pytest
from agent_core.domain.identifiers import new_session_id
from agent_integrations.ag_ui import AgUiProjectionError, AgUiProjector
from agent_integrations.ag_ui.projection_state import ProjectionState

from tests.agent_integrations.test_ag_ui_projection import _golden_events, _identity


def test_incremental_batches_match_whole_stream_frames() -> None:
    identity = _identity(new_session_id())
    events = _golden_events(identity.session_id)
    projector = AgUiProjector()
    state = ProjectionState()
    expected = list(projector.project_events(events, identity))
    actual = [
        *projector.project_events(events[:2], identity, state=state),
        *projector.project_events(events[2:5], identity, state=state),
        *projector.project_events(events[5:], identity, state=state),
    ]
    assert actual == expected
    assert state.last_sequence == events[-1].sequence
    assert state.started


@pytest.mark.parametrize("field", ["session_id", "thread_id", "run_id", "parent_run_id"])
def test_incremental_state_cannot_be_used_for_another_identity(field: str) -> None:
    identity = _identity(new_session_id())
    events = _golden_events(identity.session_id)
    projector = AgUiProjector()
    state = ProjectionState()
    list(projector.project_events(events[:1], identity, state=state))
    foreign = identity.model_copy(update={field: uuid4() if field == "session_id" else "foreign"})
    event = events[1].model_copy(update={"session_id": foreign.session_id})
    with pytest.raises(AgUiProjectionError, match="another Session/run"):
        list(projector.project_events([event], foreign, state=state))
    assert state.last_sequence == 0


def test_incremental_batches_cannot_replay_the_same_source_position() -> None:
    identity = _identity(new_session_id())
    events = _golden_events(identity.session_id)
    projector = AgUiProjector()
    state = ProjectionState()
    list(projector.project_events(events[:2], identity, state=state))
    with pytest.raises(AgUiProjectionError, match="increasing"):
        list(projector.project_events(events[1:3], identity, state=state))
    assert state.last_sequence == 1
