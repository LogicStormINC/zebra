"""Bounded journal queries; writes use the existing leased event recorder."""

from collections.abc import Callable
from time import monotonic

from agent_core.application.native_script import NativeScriptUnavailable
from agent_core.domain.events import EventActor, EventType
from agent_core.domain.identifiers import SessionId
from agent_core.domain.native_script_receipt import NativeScriptEvent
from agent_core.ports.event_store import BoundedSessionEventReadPort


class EventScriptJournal:
    def __init__(
        self,
        events: BoundedSessionEventReadPort,
        session_id: SessionId,
        append: Callable[[EventType, EventActor, dict[str, object]], object],
        check: Callable[[], None],
    ) -> None:
        self._events, self._session_id = events, session_id
        self._append, self._check = append, check

    def read(self, invocation_id: str) -> tuple[NativeScriptEvent, ...]:
        # ponytail: bounded8MiB/8192-event/2s scan fails closed above its ceiling.
        # Add a durable per-invocation index before supporting longer event streams.
        self._check()
        deadline = monotonic() + 2
        highwater = self._events.read_session_highwater(self._session_id)
        after, count, byte_count = -1, 0, 0
        result: list[NativeScriptEvent] = []
        while after < highwater:
            self._check()
            if monotonic() >= deadline or count >= 8192 or byte_count >= 8_388_608:
                raise NativeScriptUnavailable("NATIVE_SCRIPT_JOURNAL_BUDGET")
            page = self._events.read_session_event_page(
                self._session_id,
                after,
                through_sequence=highwater,
                limit=min(256, 8192 - count),
                max_bytes=min(1_048_576, 8_388_608 - byte_count),
            )
            if not page.events or page.after_sequence != after or page.highwater != highwater:
                raise NativeScriptUnavailable("NATIVE_SCRIPT_JOURNAL_INCOMPLETE")
            for event in page.events:
                if event.event_type is EventType.NATIVE_SCRIPT_INVOCATION:
                    record = NativeScriptEvent.model_validate(event.payload)
                    if record.invocation_id == invocation_id:
                        result.append(record)
            count += len(page.events)
            byte_count += page.byte_count
            after = page.events[-1].sequence
        self._check()
        return tuple(result)

    def append(self, event: NativeScriptEvent) -> None:
        self._check()
        self._append(
            EventType.NATIVE_SCRIPT_INVOCATION, EventActor.HARNESS, event.model_dump(mode="json")
        )
