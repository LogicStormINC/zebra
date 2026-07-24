from __future__ import annotations

from typing import Protocol

from agent_core.domain.session_history import SessionHistoryRequest, SessionHistoryResult


class SessionHistoryPort(Protocol):
    def scoped(
        self,
        allowed_session_ids: tuple[str, ...] | None,
    ) -> SessionHistoryPort: ...

    def query(self, request: SessionHistoryRequest) -> SessionHistoryResult: ...
