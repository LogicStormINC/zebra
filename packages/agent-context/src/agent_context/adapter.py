from datetime import datetime
from pathlib import Path

from agent_core.domain.memories import MemoryType
from agent_core.domain.messages import SessionMessage
from agent_core.ports.context_compiler import ConfirmedMemoryInput, RuntimeEvidenceInput
from agent_core.ports.conversation_compactor import ConversationCompactionResult

from agent_context.compaction import (
    ConversationCompactionRequest,
    ToolOutputCompactionRequest,
    ToolOutputEvidence,
    compact_conversation,
    compact_tool_outputs,
)
from agent_context.compiler import compile_context
from agent_context.conversation import compact_message_history
from agent_context.models import (
    ContextBudget,
    ContextCompileRequest,
    ContextItem,
    ContextItemKind,
    ContextProvenance,
)
from agent_context.prompt_layout import build_prompt_layout
from agent_context.scanner import estimate_tokens


class LocalContextCompiler:
    def compact_conversation(
        self,
        messages: tuple[SessionMessage, ...],
        *,
        user_goal: str,
        max_tokens: int,
        created_at: datetime,
    ) -> ConversationCompactionResult:
        return compact_message_history(
            messages,
            user_goal=user_goal,
            max_tokens=max_tokens,
            created_at=created_at,
        )

    def build_system_prompt(
        self,
        *,
        task_input: str,
        workspace_root: Path,
        max_tokens: int,
        runtime_evidence: tuple[RuntimeEvidenceInput, ...] = (),
        confirmed_memories: tuple[ConfirmedMemoryInput, ...] = (),
    ) -> str | None:
        evidence_items = _compact_runtime_evidence(runtime_evidence)
        memory_items = _confirmed_memory_items(confirmed_memories)
        compiled = compile_context(
            ContextCompileRequest(
                task_input=task_input,
                workspace_root=workspace_root,
                budget=ContextBudget(max_tokens=max_tokens),
                runtime_evidence_items=evidence_items,
                memory_items=memory_items,
            )
        )
        if not compiled.items:
            return None
        layout = build_prompt_layout(compiled)
        return layout.rendered_text


def _compact_runtime_evidence(
    runtime_evidence: tuple[RuntimeEvidenceInput, ...],
) -> tuple[ContextItem, ...]:
    items: list[ContextItem] = []
    planner_summaries = tuple(
        evidence.summary for evidence in runtime_evidence if evidence.kind == "planner_summary"
    )
    verifier_failures = tuple(
        evidence.summary
        for evidence in runtime_evidence
        if evidence.kind == "verifier_summary" and not bool((evidence.metadata or {}).get("passed"))
    )
    verifier_acceptance = tuple(
        evidence.summary
        for evidence in runtime_evidence
        if evidence.kind == "verifier_summary" and bool((evidence.metadata or {}).get("passed"))
    )
    for evidence in runtime_evidence:
        if evidence.kind == "conversation_summary":
            items.append(
                compact_conversation(
                    ConversationCompactionRequest(
                        user_goal=evidence.summary,
                        acceptance_criteria=verifier_acceptance,
                        current_plan=evidence.details + planner_summaries,
                        unresolved_tests=verifier_failures,
                        max_tokens=120,
                    )
                )
            )
            continue
        if evidence.kind == "tool_output_summary":
            items.append(
                compact_tool_outputs(
                    ToolOutputCompactionRequest(
                        evidences=(
                            ToolOutputEvidence(
                                tool_name="runtime_evidence",
                                output=evidence.summary,
                                artifact_uri=evidence.artifact_uri,
                            ),
                        ),
                        max_tokens=80,
                    )
                )
            )
    return tuple(items)


def _confirmed_memory_items(
    confirmed_memories: tuple[ConfirmedMemoryInput, ...],
) -> tuple[ContextItem, ...]:
    items: list[ContextItem] = []
    for index, memory in enumerate(confirmed_memories, start=1):
        text = memory.text.strip()
        if not text:
            continue
        items.append(
            ContextItem(
                kind=ContextItemKind.CONFIRMED_MEMORY,
                title=f"{_memory_type_title(memory.memory_type)} {index}",
                content=text,
                provenance=ContextProvenance(
                    source_type="confirmed_memory",
                    locator=f"confirmed_memory:{memory.memory_type.value}:{index}",
                ),
                priority=100,
                token_count=estimate_tokens(text),
            )
        )
    return tuple(items)


def _memory_type_title(memory_type: MemoryType) -> str:
    if memory_type is MemoryType.PROJECT_RULE:
        return "Project Rule"
    if memory_type is MemoryType.ARCHITECTURE_FACT:
        return "Architecture Fact"
    if memory_type is MemoryType.PROCEDURE:
        return "Procedure"
    if memory_type is MemoryType.PREFERENCE:
        return "Preference"
    if memory_type is MemoryType.EPISODIC:
        return "Episodic Memory"
    if memory_type is MemoryType.FAILED_ATTEMPT:
        return "Failed Attempt"
    return "Confirmed Memory"
