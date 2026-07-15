from typing import Protocol

from agent_core.domain.session_history import SessionHistoryRequest, SessionHistoryResult


class SessionHistoryPort(Protocol):
    def query(self, request: SessionHistoryRequest) -> SessionHistoryResult: ...
