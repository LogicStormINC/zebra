from typing import Protocol

from agent_core.domain.events import SessionEvent
from agent_core.domain.identifiers import SessionId


class EventStorePort(Protocol):
    def append(self, event: SessionEvent) -> SessionEvent: ...

    def list_for_session(self, session_id: SessionId) -> list[SessionEvent]: ...

    def read_since(
        self,
        session_id: SessionId,
        sequence: int,
    ) -> list[SessionEvent]: ...
