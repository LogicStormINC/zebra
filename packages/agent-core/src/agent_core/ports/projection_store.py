from typing import Protocol

from agent_core.domain.identifiers import SessionId
from agent_core.domain.sessions import Session


class ProjectionStorePort(Protocol):
    def save_session(self, session: Session) -> Session: ...

    def get_session(self, session_id: SessionId) -> Session | None: ...

    def list_recent_sessions(self, *, limit: int) -> list[Session]: ...

    def list_ready_sessions(self, *, limit: int) -> list[Session]: ...
