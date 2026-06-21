from pathlib import Path

from agent_core.ports.context_compiler import RuntimeEvidenceInput

from agent_context.compaction import (
    ConversationCompactionRequest,
    ToolOutputCompactionRequest,
    ToolOutputEvidence,
    compact_conversation,
    compact_tool_outputs,
)
from agent_context.compiler import compile_context
from agent_context.models import ContextBudget, ContextCompileRequest, ContextItem
from agent_context.prompt_layout import build_prompt_layout


class LocalContextCompiler:
    def build_system_prompt(
        self,
        *,
        task_input: str,
        workspace_root: Path,
        max_tokens: int,
        runtime_evidence: tuple[RuntimeEvidenceInput, ...] = (),
    ) -> str | None:
        evidence_items = _compact_runtime_evidence(runtime_evidence)
        compiled = compile_context(
            ContextCompileRequest(
                task_input=task_input,
                workspace_root=workspace_root,
                budget=ContextBudget(max_tokens=max_tokens),
                runtime_evidence_items=evidence_items,
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
    for evidence in runtime_evidence:
        if evidence.kind == "conversation_summary":
            items.append(
                compact_conversation(
                    ConversationCompactionRequest(
                        user_goal=evidence.summary,
                        current_plan=evidence.details,
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
