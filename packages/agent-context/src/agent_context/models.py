from dataclasses import dataclass, field
from enum import StrEnum
from pathlib import Path


class ContextItemKind(StrEnum):
    REPO_MAP = "repo_map"
    FILE_SNIPPET = "file_snippet"
    RELATED_FILE = "related_file"
    CONVERSATION_SUMMARY = "conversation_summary"
    TOOL_OUTPUT_SUMMARY = "tool_output_summary"


@dataclass(frozen=True)
class ContextProvenance:
    source_type: str
    locator: str

    def __post_init__(self) -> None:
        if not self.source_type.strip():
            raise ValueError("source_type must not be blank")
        if not self.locator.strip():
            raise ValueError("locator must not be blank")


@dataclass(frozen=True)
class ContextItem:
    kind: ContextItemKind
    title: str
    content: str
    provenance: ContextProvenance
    priority: int = 0
    token_count: int = 0

    def __post_init__(self) -> None:
        if not self.title.strip():
            raise ValueError("title must not be blank")
        if not self.content.strip():
            raise ValueError("content must not be blank")
        if self.priority < 0:
            raise ValueError("priority must not be negative")
        if self.token_count < 0:
            raise ValueError("token_count must not be negative")


@dataclass(frozen=True)
class ContextBudget:
    max_tokens: int

    def __post_init__(self) -> None:
        if self.max_tokens <= 0:
            raise ValueError("max_tokens must be positive")


@dataclass(frozen=True)
class ContextCompileRequest:
    task_input: str
    workspace_root: Path
    budget: ContextBudget = field(default_factory=lambda: ContextBudget(max_tokens=1200))

    def __post_init__(self) -> None:
        if not self.task_input.strip():
            raise ValueError("task_input must not be blank")
        if not self.workspace_root.is_absolute():
            raise ValueError("workspace_root must be absolute")


@dataclass(frozen=True)
class CompiledContext:
    items: tuple[ContextItem, ...]
    total_tokens: int
    truncated: bool

    def __post_init__(self) -> None:
        if self.total_tokens < 0:
            raise ValueError("total_tokens must not be negative")
