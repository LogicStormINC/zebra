"""Compatibility facades over the event-derived PostgreSQL model/tool indexes."""

from __future__ import annotations

from agent_core.domain.events import SessionEvent
from agent_core.domain.identifiers import SessionId
from agent_core.domain.model_calls import ModelCallRecord
from agent_core.domain.tool_runs import ToolRunRecord
from agent_core.ports.aggregate_mutation import WorkerMutationAuthority
from agent_core.ports.model_call_store import ModelCallStorePort
from agent_core.ports.model_tool_projection import ModelToolProjectionPort
from agent_core.ports.tool_run_store import ToolRunStorePort


class PostgresModelCallProjectionAdapter(ModelCallStorePort):
    """Expose model-call reads while keeping writes on the fenced projection."""

    def __init__(self, projection: ModelToolProjectionPort) -> None:
        self._projection = projection

    def upsert(self, record: ModelCallRecord) -> ModelCallRecord:
        raise RuntimeError("cloud model calls are Event-derived; use fenced worker indexing")

    def list_for_session(self, session_id: SessionId) -> list[ModelCallRecord]:
        return self._projection.list_model_calls(session_id)

    def index_worker_event(
        self,
        event: SessionEvent,
        *,
        authority: WorkerMutationAuthority,
    ) -> ModelCallRecord | None:
        record = self._projection.index_worker_event(event, authority=authority)
        return record if isinstance(record, ModelCallRecord) else None


class PostgresToolRunProjectionAdapter(ToolRunStorePort):
    """Expose tool-run reads while keeping writes on the fenced projection."""

    def __init__(self, projection: ModelToolProjectionPort) -> None:
        self._projection = projection

    def upsert(self, record: ToolRunRecord) -> ToolRunRecord:
        raise RuntimeError("cloud tool runs are Event-derived; use fenced worker indexing")

    def list_for_session(self, session_id: SessionId) -> list[ToolRunRecord]:
        return self._projection.list_tool_runs(session_id)

    def index_worker_event(
        self,
        event: SessionEvent,
        *,
        authority: WorkerMutationAuthority,
    ) -> ToolRunRecord | None:
        record = self._projection.index_worker_event(event, authority=authority)
        return record if isinstance(record, ToolRunRecord) else None
