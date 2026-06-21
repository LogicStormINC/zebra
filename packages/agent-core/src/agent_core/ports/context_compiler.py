from dataclasses import dataclass
from pathlib import Path
from typing import Protocol


@dataclass(frozen=True)
class RuntimeEvidenceInput:
    kind: str
    summary: str
    details: tuple[str, ...] = ()
    artifact_uri: str | None = None

    def __post_init__(self) -> None:
        if not self.kind.strip():
            raise ValueError("kind must not be blank")
        if not self.summary.strip():
            raise ValueError("summary must not be blank")
        if self.artifact_uri is not None and not self.artifact_uri.strip():
            raise ValueError("artifact_uri must not be blank when set")


class ContextCompilerPort(Protocol):
    def build_system_prompt(
        self,
        *,
        task_input: str,
        workspace_root: Path,
        max_tokens: int,
        runtime_evidence: tuple[RuntimeEvidenceInput, ...] = (),
    ) -> str | None: ...
