from datetime import UTC, datetime

from agent_core.domain.events import EventActor, EventType, SessionEvent
from agent_core.domain.identifiers import new_session_id
from agent_core.domain.messages import MessageRole
from agent_core.domain.turns import derive_turn_id
from zebra_agent_worker.task_recovery import _conversation_history

NOW = datetime(2026, 8, 30, 0, 0, tzinfo=UTC)


def _event(
    sequence: int,
    event_type: EventType,
    payload: dict[str, object],
) -> SessionEvent:
    return SessionEvent.create(
        session_id=SESSION_ID,
        sequence=sequence,
        event_type=event_type,
        actor=EventActor.HARNESS,
        payload=payload,
        created_at=NOW,
    )


SESSION_ID = new_session_id()


def test_conversation_history_recovers_completed_turns_before_current_input() -> None:
    events = [
        _event(0, EventType.USER_MESSAGE_RECEIVED, {"content": "暗号是海风"}),
        _event(
            1,
            EventType.TURN_COMPLETED,
            {
                "turn_id": str(derive_turn_id(SESSION_ID, 0)),
                "turn_index": 0,
                "metadata": {"assistant_message": "我记住了。"},
            },
        ),
        _event(2, EventType.USER_MESSAGE_RECEIVED, {"content": "暗号是什么？"}),
    ]

    history = _conversation_history(events, before_sequence=2)

    assert [(message.role, message.content) for message in history] == [
        (MessageRole.USER, "暗号是海风"),
        (MessageRole.ASSISTANT, "我记住了。"),
    ]
