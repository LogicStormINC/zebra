from typing import Protocol

from agent_core.domain.events import SessionEvent
from agent_core.domain.identifiers import SessionId
from agent_core.domain.model_calls import ModelCallRecord
from agent_core.domain.tool_runs import ToolRunRecord
from agent_core.ports.aggregate_mutation import WorkerMutationAuthority


class ModelToolProjectionPort(Protocol):
    """Event-derived Model/Tool index used by the cloud storage profile."""

    def index_worker_event(
        self, event: SessionEvent, *, authority: WorkerMutationAuthority
    ) -> ModelCallRecord | ToolRunRecord | None: ...

    def replay_session(self, session_id: SessionId) -> int: ...

    def list_model_calls(self, session_id: SessionId) -> list[ModelCallRecord]: ...

    def list_tool_runs(self, session_id: SessionId) -> list[ToolRunRecord]: ...
