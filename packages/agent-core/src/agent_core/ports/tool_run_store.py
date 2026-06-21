from typing import Protocol

from agent_core.domain.identifiers import SessionId
from agent_core.domain.tool_runs import ToolRunRecord


class ToolRunStorePort(Protocol):
    def upsert(self, record: ToolRunRecord) -> ToolRunRecord: ...

    def list_for_session(self, session_id: SessionId) -> list[ToolRunRecord]: ...
