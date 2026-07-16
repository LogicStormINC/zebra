from dataclasses import dataclass, field
from enum import StrEnum
from pathlib import Path


class ContextItemKind(StrEnum):
    REPO_MAP = "repo_map"
    CONFIRMED_MEMORY = "confirmed_memory"
    FILE_SNIPPET = "file_snippet"
    RELATED_FILE = "related_file"
    CONVERSATION_SUMMARY = "conversation_summary"
    TOOL_OUTPUT_SUMMARY = "tool_output_summary"
    USER_ATTACHMENT = "user_attachment"
    MCP_RESOURCE = "mcp_resource"
    MCP_PROMPT = "mcp_prompt"


RUNTIME_EVIDENCE_KINDS = frozenset(
    {
        ContextItemKind.CONVERSATION_SUMMARY,
        ContextItemKind.TOOL_OUTPUT_SUMMARY,
    }
)
RUNTIME_EVIDENCE_SOURCE_TYPES = frozenset({"session_projection", "tool_trace"})
MEMORY_SOURCE_TYPES = frozenset({"confirmed_memory"})
ATTACHMENT_SOURCE_TYPES = frozenset({"user_attachment", "mcp_resource", "mcp_prompt"})


class TrustLevel(StrEnum):
    SYSTEM = "system"
    TRUSTED = "trusted"
    USER = "user"
    UNTRUSTED = "untrusted"


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
    trust_level: TrustLevel = TrustLevel.UNTRUSTED
    priority: int = 0
    token_count: int = 0
    metadata: dict[str, object] = field(default_factory=dict)

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
    runtime_evidence_items: tuple[ContextItem, ...] = ()
    memory_items: tuple[ContextItem, ...] = ()
    attachment_items: tuple[ContextItem, ...] = ()

    def __post_init__(self) -> None:
        if not self.task_input.strip():
            raise ValueError("task_input must not be blank")
        if not self.workspace_root.is_absolute():
            raise ValueError("workspace_root must be absolute")
        if not self.workspace_root.exists():
            raise ValueError("workspace_root must exist")
        if not self.workspace_root.is_dir():
            raise ValueError("workspace_root must be a directory")
        for item in self.runtime_evidence_items:
            if item.kind not in RUNTIME_EVIDENCE_KINDS:
                raise ValueError(
                    "runtime_evidence_items must use conversation or tool-output summary kinds"
                )
            if item.provenance.source_type not in RUNTIME_EVIDENCE_SOURCE_TYPES:
                raise ValueError(
                    "runtime_evidence_items must come from session projection or tool trace"
                )
        for item in self.memory_items:
            if item.kind is not ContextItemKind.CONFIRMED_MEMORY:
                raise ValueError("memory_items must use confirmed_memory kind")
            if item.provenance.source_type not in MEMORY_SOURCE_TYPES:
                raise ValueError("memory_items must come from confirmed_memory sources")
        for item in self.attachment_items:
            if item.kind not in {
                ContextItemKind.USER_ATTACHMENT,
                ContextItemKind.MCP_RESOURCE,
                ContextItemKind.MCP_PROMPT,
            }:
                raise ValueError("attachment_items must use an attachment context kind")
            if item.provenance.source_type not in ATTACHMENT_SOURCE_TYPES:
                raise ValueError("attachment_items must come from supported attachment sources")


@dataclass(frozen=True)
class CompiledContext:
    items: tuple[ContextItem, ...]
    total_tokens: int
    truncated: bool

    def __post_init__(self) -> None:
        if self.total_tokens < 0:
            raise ValueError("total_tokens must not be negative")
