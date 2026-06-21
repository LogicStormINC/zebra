from pathlib import Path

from agent_context import (
    ContextBudget,
    ContextCompileRequest,
    ContextItemKind,
    ConversationCompactionRequest,
    ToolOutputCompactionRequest,
    ToolOutputEvidence,
    build_prompt_layout,
    compact_conversation,
    compact_tool_outputs,
    compile_context,
)


def test_compile_context_includes_runtime_evidence_items(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    (workspace / "README.md").write_text("Project overview.\n", encoding="utf-8")

    conversation_item = compact_conversation(
        ConversationCompactionRequest(
            user_goal="Fix failing smoke tests.",
            current_plan=("inspect logs", "patch code"),
            max_tokens=120,
        )
    )
    tool_item = compact_tool_outputs(
        ToolOutputCompactionRequest(
            evidences=(
                ToolOutputEvidence(
                    tool_name="tests.run",
                    output="2 failed, 14 passed",
                ),
            ),
            max_tokens=80,
        )
    )

    compiled = compile_context(
        ContextCompileRequest(
            task_input="fix smoke tests",
            workspace_root=workspace.resolve(),
            budget=ContextBudget(max_tokens=240),
            runtime_evidence_items=(conversation_item, tool_item),
        )
    )

    kinds = {item.kind for item in compiled.items}

    assert ContextItemKind.CONVERSATION_SUMMARY in kinds
    assert ContextItemKind.TOOL_OUTPUT_SUMMARY in kinds


def test_runtime_evidence_flows_to_dynamic_prompt_section(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    (workspace / "AGENTS.md").write_text("Repository rules.\n", encoding="utf-8")

    conversation_item = compact_conversation(
        ConversationCompactionRequest(
            user_goal="Review repo constraints.",
            max_tokens=80,
        )
    )

    compiled = compile_context(
        ContextCompileRequest(
            task_input="review constraints",
            workspace_root=workspace.resolve(),
            budget=ContextBudget(max_tokens=160),
            runtime_evidence_items=(conversation_item,),
        )
    )
    layout = build_prompt_layout(compiled)

    assert any(
        item.kind is ContextItemKind.CONVERSATION_SUMMARY
        for item in layout.dynamic.items
    )
