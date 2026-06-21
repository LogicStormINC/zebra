from dataclasses import dataclass

from agent_context.models import ContextItem, ContextItemKind, ContextProvenance, TrustLevel
from agent_context.scanner import estimate_tokens


@dataclass(frozen=True)
class ToolOutputEvidence:
    tool_name: str
    output: str
    artifact_uri: str | None = None

    def __post_init__(self) -> None:
        if not self.tool_name.strip():
            raise ValueError("tool_name must not be blank")
        if not self.output.strip():
            raise ValueError("output must not be blank")
        if self.artifact_uri is not None and not self.artifact_uri.strip():
            raise ValueError("artifact_uri must not be blank when set")


@dataclass(frozen=True)
class ConversationCompactionRequest:
    user_goal: str
    acceptance_criteria: tuple[str, ...] = ()
    confirmed_constraints: tuple[str, ...] = ()
    current_plan: tuple[str, ...] = ()
    modified_files: tuple[str, ...] = ()
    failed_attempts: tuple[str, ...] = ()
    unresolved_tests: tuple[str, ...] = ()
    approvals: tuple[str, ...] = ()
    artifact_refs: tuple[str, ...] = ()
    max_tokens: int = 240

    def __post_init__(self) -> None:
        if not self.user_goal.strip():
            raise ValueError("user_goal must not be blank")
        if self.max_tokens <= 0:
            raise ValueError("max_tokens must be positive")


@dataclass(frozen=True)
class ToolOutputCompactionRequest:
    evidences: tuple[ToolOutputEvidence, ...]
    max_tokens: int = 160

    def __post_init__(self) -> None:
        if self.max_tokens <= 0:
            raise ValueError("max_tokens must be positive")


def compact_conversation(
    request: ConversationCompactionRequest,
) -> ContextItem:
    sections = [
        _section("User Goal", (request.user_goal,)),
        _section("Acceptance", request.acceptance_criteria),
        _section("Constraints", request.confirmed_constraints),
        _section("Plan", request.current_plan),
        _section("Modified Files", request.modified_files),
        _section("Failed Attempts", request.failed_attempts),
        _section("Unresolved Tests", request.unresolved_tests),
        _section("Approvals", request.approvals),
        _section("Artifacts", request.artifact_refs),
    ]
    content = _truncate("\n\n".join(section for section in sections if section), request.max_tokens)
    return ContextItem(
        kind=ContextItemKind.CONVERSATION_SUMMARY,
        title="Conversation Summary",
        content=content,
        provenance=ContextProvenance(
            source_type="session_projection",
            locator="conversation_compaction",
        ),
        trust_level=TrustLevel.USER,
        priority=95,
        token_count=estimate_tokens(content),
        metadata={"instruction_boundary": "data", "prompt_injection_risk": False},
    )


def compact_tool_outputs(
    request: ToolOutputCompactionRequest,
) -> ContextItem:
    if not request.evidences:
        content = "No tool output evidence recorded."
    else:
        lines = []
        for evidence in request.evidences:
            artifact = f" artifact={evidence.artifact_uri}" if evidence.artifact_uri else ""
            lines.append(
                f"- {evidence.tool_name}: {_single_line(evidence.output)}{artifact}"
            )
        content = _truncate("Tool Output Summary\n" + "\n".join(lines), request.max_tokens)
    return ContextItem(
        kind=ContextItemKind.TOOL_OUTPUT_SUMMARY,
        title="Tool Output Summary",
        content=content,
        provenance=ContextProvenance(
            source_type="tool_trace",
            locator="tool_output_compaction",
        ),
        trust_level=TrustLevel.USER,
        priority=90,
        token_count=estimate_tokens(content),
        metadata={"instruction_boundary": "data", "prompt_injection_risk": False},
    )


def _section(title: str, entries: tuple[str, ...]) -> str:
    cleaned = [entry.strip() for entry in entries if entry.strip()]
    if not cleaned:
        return ""
    return title + ":\n" + "\n".join(f"- {entry}" for entry in cleaned)


def _truncate(content: str, max_tokens: int) -> str:
    max_chars = max_tokens * 4
    if len(content) <= max_chars:
        return content
    return content[: max_chars - 3].rstrip() + "..."


def _single_line(content: str) -> str:
    return " ".join(part.strip() for part in content.splitlines() if part.strip())
