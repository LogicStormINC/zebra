"""Native Core diagnostic only, no DB, model or business execution."""

import overlay_imports as overlay_imports

# isort: split

from pathlib import Path

from agent_core.application import (
    SessionMessageAppendCommand,
    SessionMessageAppendService,
    current_turn,
    project_turns,
)
from agent_core.application.session_bootstrap import (
    SessionBootstrapCommand,
    SessionBootstrapService,
)
from agent_core.application.session_projection import apply_event
from agent_core.domain.events import EventActor, EventType, SessionEvent
from agent_core.domain.turns import InteractionMode, derive_turn_id

boot = SessionBootstrapService().build(
    SessionBootstrapCommand(
        title="QA diagnostic",
        user_input="QA seed",
        workspace_root=Path("/synthetic-qa"),
        interaction_mode=InteractionMode.CONVERSATION,
    )
)
turns = project_turns(boot.events)
assert current_turn(boot.events) is not None
try:
    SessionMessageAppendService().build_event(
        session=boot.session,
        next_sequence=3,
        command=SessionMessageAppendCommand(
            content="QA followup", prior_human_turns=len(turns), open_turn_exists=True
        ),
    )
except ValueError as error:
    assert str(error) == "turn_in_progress"
else:
    raise AssertionError("two open Turns accepted")
completed = SessionEvent.create(
    session_id=boot.session.session_id,
    sequence=3,
    event_type=EventType.TURN_COMPLETED,
    actor=EventActor.HARNESS,
    payload=dict(
        turn_id=str(derive_turn_id(boot.session.session_id, 0)),
        turn_index=0,
        summary="synthetic QA prior turn",
        closes_segment=False,
    ),
)
turns = project_turns((*boot.events, completed))
assert current_turn((*boot.events, completed)) is None
followup = SessionMessageAppendService().build_event(
    session=apply_event(boot.session, completed),
    next_sequence=4,
    command=SessionMessageAppendCommand(
        content="QA followup", prior_human_turns=len(turns), open_turn_exists=False
    ),
)
assert (
    followup.event_type is EventType.USER_MESSAGE_RECEIVED and followup.payload["turn_index"] == 1
)
print(
    "PASS native Core: initial MESSAGE refuses turn_in_progress; synt"
    "hetic completed conversation Turn permits followup, no Core weak"
    "ening"
)
