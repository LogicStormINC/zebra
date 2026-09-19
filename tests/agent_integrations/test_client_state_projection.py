"""Client page state projects only into its owned AG-UI namespace."""

import json
from datetime import UTC, datetime
from hashlib import sha256

from ag_ui.core import StateDeltaEvent
from agent_core.contracts import SessionCommand, SessionCommandKind
from agent_core.domain.events import EventActor, EventType, SessionEvent
from agent_core.domain.identifiers import new_session_id
from agent_integrations.ag_ui import AgUiProjector, AgUiRunIdentity


def test_client_state_projects_under_client_namespace() -> None:
    session_id = new_session_id()
    state = {"trench.ui.route": {"pathname": "/dashboard/strategy"}}
    digest = sha256(json.dumps(state, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
    command = SessionCommand(
        session_id=session_id,
        kind=SessionCommandKind.RUN,
        expected_revision=0,
        idempotency_key="client-state-projection",
        payload={
            "thread_id": "task-1",
            "run_id": "run-1",
            "client": {
                "frontend_app_id": "trench-web",
                "profile_digest": "a" * 64,
                "ui_revision": 4,
                "state_snapshot": state,
                "state_digest": digest,
            },
        },
    )
    event = SessionEvent.create(
        session_id=session_id,
        sequence=0,
        event_type=EventType.SESSION_COMMAND_ACCEPTED,
        actor=EventActor.USER,
        payload=command.event_payload(),
        created_at=datetime.now(UTC),
    )

    projection = AgUiProjector().project(
        (event,),
        AgUiRunIdentity(session_id=session_id, thread_id="task-1", run_id="run-1"),
    )

    delta = next(item for item in projection.events if isinstance(item, StateDeltaEvent))
    assert delta.delta[0]["path"] == "/client"
    assert delta.delta[0]["value"]["owner"] == "host_frontend"
    assert delta.delta[0]["value"]["readables"] == state


def test_digest_drift_is_not_projected() -> None:
    session_id = new_session_id()
    command = SessionCommand(
        session_id=session_id,
        kind=SessionCommandKind.RUN,
        expected_revision=0,
        idempotency_key="client-state-drift",
        payload={
            "client": {
                "state_snapshot": {"trench.ui.route": {"pathname": "/"}},
                "state_digest": "0" * 64,
            }
        },
    )
    event = SessionEvent.create(
        session_id=session_id,
        sequence=0,
        event_type=EventType.SESSION_COMMAND_ACCEPTED,
        actor=EventActor.USER,
        payload=command.event_payload(),
    )

    projection = AgUiProjector().project(
        (event,),
        AgUiRunIdentity(session_id=session_id, thread_id="task-1", run_id="run-1"),
    )

    assert not any(isinstance(item, StateDeltaEvent) for item in projection.events)
