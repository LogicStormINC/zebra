from typing import Protocol

from agent_core.domain.identifiers import SessionId
from agent_core.domain.model_calls import ModelCallRecord


class ModelCallStorePort(Protocol):
    def upsert(self, record: ModelCallRecord) -> ModelCallRecord: ...

    def list_for_session(self, session_id: SessionId) -> list[ModelCallRecord]: ...
