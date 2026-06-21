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
    planner_summaries = tuple(
        evidence.summary
        for evidence in runtime_evidence
        if evidence.kind == "planner_summary"
    )
    verifier_failures = tuple(
        evidence.summary
        for evidence in runtime_evidence
        if evidence.kind == "verifier_summary"
        and not bool((evidence.metadata or {}).get("passed"))
    )
    verifier_acceptance = tuple(
        evidence.summary
        for evidence in runtime_evidence
        if evidence.kind == "verifier_summary"
        and bool((evidence.metadata or {}).get("passed"))
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
