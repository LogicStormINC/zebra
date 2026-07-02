from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

from agent_core.domain.memories import MemoryType


@dataclass(frozen=True)
class RuntimeEvidenceInput:
    kind: str
    summary: str
    details: tuple[str, ...] = ()
    metadata: dict[str, object] | None = None
    artifact_uri: str | None = None

    def __post_init__(self) -> None:
        if not self.kind.strip():
            raise ValueError("kind must not be blank")
        if not self.summary.strip():
            raise ValueError("summary must not be blank")
        if self.artifact_uri is not None and not self.artifact_uri.strip():
            raise ValueError("artifact_uri must not be blank when set")


@dataclass(frozen=True)
class ConfirmedMemoryInput:
    memory_type: MemoryType
    text: str

    def __post_init__(self) -> None:
        if not self.text.strip():
            raise ValueError("text must not be blank")


class ContextCompilerPort(Protocol):
    def build_system_prompt(
        self,
        *,
        task_input: str,
        workspace_root: Path,
        max_tokens: int,
        runtime_evidence: tuple[RuntimeEvidenceInput, ...] = (),
        confirmed_memories: tuple[ConfirmedMemoryInput, ...] = (),
    ) -> str | None: ...
