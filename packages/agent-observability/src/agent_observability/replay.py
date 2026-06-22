from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from agent_observability.models import TraceRecord


class TraceReader(Protocol):
    def list(self) -> tuple[TraceRecord, ...]: ...


@dataclass(frozen=True)
class ReplayResult:
    session_id: str
    event_count: int
    tool_result_count: int
    audit_steps: int
    model_calls: int
    total_tokens: int
    cost_usd: float


@dataclass(frozen=True)
class LocalReplayRunner:
    def replay(self, trace: TraceRecord) -> ReplayResult:
        if trace.event_count <= 0:
            raise ValueError("replay requires at least one traced event")
        return ReplayResult(
            session_id=trace.session_id,
            event_count=trace.event_count,
            tool_result_count=trace.tool_result_count,
            audit_steps=len(trace.audit),
            model_calls=trace.cost.model_calls,
            total_tokens=trace.cost.total_tokens,
            cost_usd=trace.cost.cost_usd,
        )

    def replay_store(self, store: TraceReader) -> tuple[ReplayResult, ...]:
        return tuple(self.replay(trace) for trace in store.list())
