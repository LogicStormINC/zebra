from datetime import UTC, datetime

from agent_core.application.session_title import SessionTitleService
from agent_core.domain.events import EventActor, EventType, SessionEvent
from agent_core.domain.identifiers import new_message_id, new_session_id
from agent_core.domain.messages import MessageRole, SessionMessage
from agent_core.domain.modeling import ModelCompletion, ModelToolDefinition
from agent_core.domain.sessions import Session
from agent_core.ports.model_gateway import ModelGatewayPort

_CREATED_AT = datetime(2026, 7, 22, 10, 0, tzinfo=UTC)


class _ScriptedGateway(ModelGatewayPort):
    def __init__(self, text: str) -> None:
        self._text = text
        self.calls = 0

    def complete(
        self,
        messages: list[SessionMessage],
        *,
        tools: tuple[ModelToolDefinition, ...] = (),
    ) -> ModelCompletion:
        self.calls += 1
        return ModelCompletion(
            assistant_message=SessionMessage(
                message_id=new_message_id(),
                role=MessageRole.ASSISTANT,
                content=self._text,
                created_at=_CREATED_AT,
            )
        )


class _FailingGateway(ModelGatewayPort):
    def complete(
        self,
        messages: list[SessionMessage],
        *,
        tools: tuple[ModelToolDefinition, ...] = (),
    ) -> ModelCompletion:
        raise RuntimeError("model unavailable")


class _CapturingGateway(_ScriptedGateway):
    def __init__(self, text: str) -> None:
        super().__init__(text)
        self.messages: list[SessionMessage] = []

    def complete(
        self,
        messages: list[SessionMessage],
        *,
        tools: tuple[ModelToolDefinition, ...] = (),
    ) -> ModelCompletion:
        self.messages = messages
        return super().complete(messages, tools=tools)


def _session(title: str) -> Session:
    return Session.create(title=title, created_at=_CREATED_AT).model_copy(
        update={"session_id": new_session_id(), "updated_at": _CREATED_AT}
    )


def _exchange_events(session: Session) -> list[SessionEvent]:
    return [
        SessionEvent.create(
            session_id=session.session_id,
            sequence=0,
            event_type=EventType.USER_MESSAGE_RECEIVED,
            actor=EventActor.USER,
            payload={"content": "help me translate the README install steps to English"},
            created_at=_CREATED_AT,
        ),
        SessionEvent.create(
            session_id=session.session_id,
            sequence=1,
            event_type=EventType.MODEL_RESPONSE_RECEIVED,
            actor=EventActor.HARNESS,
            payload={"assistant_message": "Done — translated the install section."},
            created_at=_CREATED_AT,
        ),
    ]


def test_generate_returns_title_update_event() -> None:
    session = _session("help me translate the READ")
    gateway = _ScriptedGateway("Translate README install steps")
    service = SessionTitleService(gateway)

    event = service.generate(
        session=session,
        events=_exchange_events(session),
        next_sequence=2,
    )

    assert event is not None
    assert event.event_type is EventType.SESSION_TITLE_UPDATED
    assert event.actor is EventActor.HARNESS
    assert event.sequence == 2
    assert event.payload["title"] == "Translate README install steps"
    assert gateway.calls == 1


def test_generate_requests_an_outcome_summary_instead_of_echoing_the_question() -> None:
    session = _session("New Task")
    gateway = _CapturingGateway("README translation completed")
    service = SessionTitleService(gateway)

    event = service.generate(
        session=session,
        events=_exchange_events(session),
        next_sequence=2,
    )

    assert event is not None
    assert "outcome-oriented summary title" in gateway.messages[0].content
    assert "Do not copy or lightly shorten the user's question" in gateway.messages[0].content
    assert "Done — translated the install section" in gateway.messages[1].content


def test_generate_strips_quotes_and_title_prefix() -> None:
    session = _session("placeholder")
    service = SessionTitleService(_ScriptedGateway('Title: "Fix login bug"'))

    event = service.generate(
        session=session,
        events=_exchange_events(session),
        next_sequence=2,
    )

    assert event is not None
    assert event.payload["title"] == "Fix login bug"


def test_generate_truncates_overlong_title() -> None:
    session = _session("placeholder")
    service = SessionTitleService(_ScriptedGateway("x" * 200))

    event = service.generate(
        session=session,
        events=_exchange_events(session),
        next_sequence=2,
    )

    assert event is not None
    assert len(event.payload["title"]) <= 40


def test_generate_is_idempotent_when_title_already_updated() -> None:
    session = _session("placeholder")
    gateway = _ScriptedGateway("Should not be used")
    service = SessionTitleService(gateway)
    events = [
        *_exchange_events(session),
        SessionEvent.create(
            session_id=session.session_id,
            sequence=2,
            event_type=EventType.SESSION_TITLE_UPDATED,
            actor=EventActor.HARNESS,
            payload={"title": "Existing semantic title", "format_version": 3},
            created_at=_CREATED_AT,
        ),
    ]

    event = service.generate(session=session, events=events, next_sequence=3)

    assert event is None
    assert gateway.calls == 0


def test_generate_refreshes_legacy_question_style_title_once() -> None:
    session = _session("查看tibo最近帖子")
    service = SessionTitleService(_ScriptedGateway("Tibo帖子同步完成"))
    events = [
        *_exchange_events(session),
        SessionEvent.create(
            session_id=session.session_id,
            sequence=2,
            event_type=EventType.SESSION_TITLE_UPDATED,
            actor=EventActor.HARNESS,
            payload={"title": "查看tibo最近帖子"},
            created_at=_CREATED_AT,
        ),
    ]

    event = service.generate(session=session, events=events, next_sequence=3)

    assert event is not None
    assert event.payload == {"title": "Tibo帖子同步完成", "format_version": 3}


def test_generate_returns_none_without_user_message() -> None:
    session = _session("placeholder")
    service = SessionTitleService(_ScriptedGateway("unused"))

    event = service.generate(session=session, events=[], next_sequence=1)

    assert event is None


def test_generate_returns_none_on_model_failure() -> None:
    session = _session("placeholder")
    service = SessionTitleService(_FailingGateway())

    event = service.generate(
        session=session,
        events=_exchange_events(session),
        next_sequence=2,
    )

    assert event is None


def test_generate_returns_none_when_title_matches_existing() -> None:
    session = _session("Translate README")
    service = SessionTitleService(_ScriptedGateway("Translate README"))

    event = service.generate(
        session=session,
        events=_exchange_events(session),
        next_sequence=2,
    )

    assert event is None
