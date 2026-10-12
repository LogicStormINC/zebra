from typing import Protocol, runtime_checkable

from agent_core.domain.events import SessionEvent
from agent_core.domain.identifiers import SessionId
from agent_core.domain.sessions import SessionStatus
from agent_core.ports.session_recovery import SessionEventPage


class EventStorePort(Protocol):
    def append(self, event: SessionEvent) -> SessionEvent: ...

    def list_for_session(self, session_id: SessionId) -> list[SessionEvent]: ...

    def read_since(
        self,
        session_id: SessionId,
        sequence: int,
    ) -> list[SessionEvent]: ...


@runtime_checkable
class BoundedSessionEventReadPort(Protocol):
    """Canonical metadata and byte-admitted pages; observation never repairs."""

    def read_session_highwater(self, session_id: SessionId) -> int: ...

    def read_session_status(self, session_id: SessionId) -> SessionStatus: ...

    def read_session_event_page(
        self,
        session_id: SessionId,
        after_sequence: int,
        *,
        through_sequence: int | None = None,
        limit: int = 256,
        max_bytes: int = 1_048_576,
    ) -> SessionEventPage: ...
