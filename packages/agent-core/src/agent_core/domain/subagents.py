from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path

from agent_core.domain.identifiers import SubagentId


class SubagentStatus(StrEnum):
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


@dataclass(frozen=True)
class ResearchSource:
    reference: str
    kind: str

    def __post_init__(self) -> None:
        if not self.reference.strip() or not self.kind.strip():
            raise ValueError("research source fields must not be blank")


@dataclass(frozen=True)
class ResearchSubagentTask:
    objective: str
    workspace_root: Path
    max_model_calls: int = 3
    max_tool_calls: int = 2
    depth: int = 1

    def __post_init__(self) -> None:
        if not self.objective.strip():
            raise ValueError("research objective must not be blank")
        if not self.workspace_root.is_absolute():
            raise ValueError("research workspace_root must be absolute")
        if self.max_model_calls <= 0 or self.max_tool_calls <= 0:
            raise ValueError("research budgets must be positive")
        if self.depth <= 0:
            raise ValueError("research depth must be positive")


@dataclass(frozen=True)
class ResearchSubagentResult:
    subagent_id: SubagentId
    status: SubagentStatus
    summary: str
    sources: tuple[ResearchSource, ...] = ()
    confidence: float = 0.0
    model_calls_used: int = 0
    tool_calls_used: int = 0
    provenance: str = "local_read_only_research"

    def __post_init__(self) -> None:
        if not self.summary.strip():
            raise ValueError("research result summary must not be blank")
        if not 0.0 <= self.confidence <= 1.0:
            raise ValueError("research confidence must be between zero and one")
        if self.model_calls_used < 0 or self.tool_calls_used < 0:
            raise ValueError("research usage cannot be negative")
        if not self.provenance.strip():
            raise ValueError("research provenance must not be blank")
