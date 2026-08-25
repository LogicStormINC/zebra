"""Client effects project as replayable AG-UI state, never executable secrets."""

from datetime import UTC, datetime

from ag_ui.core import StateDeltaEvent
from agent_core.domain.events import EventActor, EventType, SessionEvent
from agent_core.domain.identifiers import new_session_id
from agent_integrations.ag_ui import AgUiProjector, AgUiRunIdentity


def test_scheduled_effect_projects_client_only_state_without_fence() -> None:
    session_id = new_session_id()
    event = SessionEvent.create(
        session_id=session_id,
        sequence=0,
        event_type=EventType.CLIENT_EFFECT_SCHEDULED,
        actor=EventActor.TOOL,
        payload={
            "attempt_number": 1,
            "tool_name": "app.ui.item.open",
            "tool_call_id": "call-1",
            "client_effect_id": "effect-1",
            "action_name": "app.ui.item.open",
            "arguments": {"itemId": "item-1"},
            "action_contract_digest": "a" * 64,
            "client_binding_digest": "b" * 64,
            "expected_ui_revision": 3,
            "request_digest": "c" * 64,
        },
        created_at=datetime.now(UTC),
    )
    identity = AgUiRunIdentity(thread_id="task-1", run_id="run-1", session_id=session_id)

    projection = AgUiProjector().project((event,), identity)

    delta = next(item for item in projection.events if isinstance(item, StateDeltaEvent))
    value = delta.delta[0]["value"]
    assert value["execution_location"] == "client"
    assert value["arguments"] == {"itemId": "item-1"}
    assert "fence" not in str(value).lower()


def test_terminal_receipt_removes_effect_on_exact_cursor_replay() -> None:
    session_id = new_session_id()
    now = datetime.now(UTC)
    scheduled = SessionEvent.create(
        session_id=session_id,
        sequence=0,
        event_type=EventType.CLIENT_EFFECT_SCHEDULED,
        actor=EventActor.TOOL,
        payload={
            "attempt_number": 1,
            "tool_name": "app.ui.item.open",
            "tool_call_id": "call-1",
            "client_effect_id": "effect-1",
            "action_name": "app.ui.item.open",
        },
        created_at=now,
    )
    terminal = SessionEvent.create(
        session_id=session_id,
        sequence=1,
        event_type=EventType.CLIENT_EFFECT_RECEIPT_ACCEPTED,
        actor=EventActor.TOOL,
        payload={
            "client_effect_id": "effect-1",
            "receipt_id": "receipt-1",
            "status": "succeeded",
        },
        created_at=now,
    )
    identity = AgUiRunIdentity(thread_id="task-1", run_id="run-1", session_id=session_id)
    first = AgUiProjector().project((scheduled,), identity)

    replay = AgUiProjector().project((scheduled, terminal), identity, after=first.next_cursor)

    delta = next(item for item in replay.events if isinstance(item, StateDeltaEvent))
    assert delta.delta == [{"op": "remove", "path": "/zebra/clientEffects/effect-1"}]
