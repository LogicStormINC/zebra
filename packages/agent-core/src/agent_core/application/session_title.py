from __future__ import annotations

from datetime import UTC, datetime

from agent_core.domain.events import EventActor, EventType, SessionEvent
from agent_core.domain.identifiers import new_message_id
from agent_core.domain.messages import MessageRole, SessionMessage
from agent_core.domain.sessions import Session
from agent_core.ports.model_gateway import ModelGatewayPort

_MAX_TITLE_CHARS = 40
_MAX_PROMPT_MESSAGE_CHARS = 2000
_TITLE_FORMAT_VERSION = 3

_SYSTEM_PROMPT = (
    "You name completed conversations. Given the user's first request and the "
    "assistant's reply, produce a short outcome-oriented summary title. Capture "
    "the topic plus the result, state, or action completed in the reply. Do not "
    "copy or lightly shorten the user's question. Use a completed-result noun "
    "phrase, not a request or to-do phrase. For example, turn '查询 tibo 最近三帖' "
    "into 'Tibo最新三帖已整理', and '查看昨天发生了什么' into '昨日订阅事件已汇总'. "
    "Never start a Chinese title with 请, 查询, 查看, 帮我, or 能否. Rules: reply with the title "
    "only, no quotes, no punctuation at the end, at most 6 words (or ~24 "
    "characters for CJK text). Use the same language as the user. Do not add "
    "prefixes like 'Title:'."
)


class SessionTitleService:
    """Generate a semantic session title from the first user/assistant exchange.

    Mirrors :class:`MemoryCandidateExtractionService`: it reads the session and its
    events and returns an event to append (or ``None`` when nothing should change).
    The operation is best-effort — any failure degrades to ``None`` so the caller
    keeps the placeholder title instead of failing the session.
    """

    def __init__(self, model_gateway: ModelGatewayPort) -> None:
        self._model_gateway = model_gateway

    def generate(
        self,
        *,
        session: Session,
        events: list[SessionEvent],
        next_sequence: int,
    ) -> SessionEvent | None:
        # Regenerate once when the title contract changes, then remain idempotent.
        if any(
            event.event_type is EventType.SESSION_TITLE_UPDATED
            and event.payload.get("format_version") == _TITLE_FORMAT_VERSION
            for event in events
        ):
            return None

        user_text = _first_text(events, EventType.USER_MESSAGE_RECEIVED, "content")
        assistant_text = _first_text(
            events, EventType.MODEL_RESPONSE_RECEIVED, "assistant_message"
        )
        if not user_text:
            return None

        try:
            title = self._request_title(user_text, assistant_text)
        except Exception:
            # Best-effort: a model/transport failure must not break finalization.
            return None
        if not title or title == session.title:
            return None

        return SessionEvent.create(
            session_id=session.session_id,
            sequence=next_sequence,
            event_type=EventType.SESSION_TITLE_UPDATED,
            actor=EventActor.HARNESS,
            payload={"title": title, "format_version": _TITLE_FORMAT_VERSION},
            created_at=session.updated_at,
        )

    def _request_title(self, user_text: str, assistant_text: str | None) -> str | None:
        now = datetime.now(UTC)
        prompt = f"User request:\n{_clip(user_text)}"
        if assistant_text:
            prompt += f"\n\nAssistant reply:\n{_clip(assistant_text)}"
        prompt += "\n\nTitle:"
        messages = [
            SessionMessage(
                message_id=new_message_id(),
                role=MessageRole.SYSTEM,
                content=_SYSTEM_PROMPT,
                created_at=now,
            ),
            SessionMessage(
                message_id=new_message_id(),
                role=MessageRole.USER,
                content=prompt,
                created_at=now,
            ),
        ]
        completion = self._model_gateway.complete(messages)
        return _normalize_title(completion.assistant_message.content)


def _first_text(
    events: list[SessionEvent], event_type: EventType, key: str
) -> str | None:
    for event in events:
        if event.event_type is not event_type:
            continue
        value = event.payload.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return None


def _clip(text: str) -> str:
    if len(text) <= _MAX_PROMPT_MESSAGE_CHARS:
        return text
    return text[:_MAX_PROMPT_MESSAGE_CHARS]


def _normalize_title(raw: str) -> str | None:
    title = raw.strip()
    # Some models echo a "Title: ..." prefix despite instructions.
    for prefix in ("Title:", "title:", "标题:", "标题："):
        if title.startswith(prefix):
            title = title[len(prefix) :].strip()
    title = title.splitlines()[0].strip() if title else title
    title = title.strip("\"'“”‘’`").strip()
    if not title:
        return None
    if len(title) > _MAX_TITLE_CHARS:
        title = title[:_MAX_TITLE_CHARS].rstrip()
    return title or None
