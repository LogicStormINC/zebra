from agent_context import (
    ContextItemKind,
    ConversationCompactionRequest,
    ToolOutputCompactionRequest,
    ToolOutputEvidence,
    compact_conversation,
    compact_tool_outputs,
)


def test_compact_conversation_preserves_required_sections() -> None:
    item = compact_conversation(
        ConversationCompactionRequest(
            user_goal="Ship context compiler MVP.",
            acceptance_criteria=("tests pass", "docs updated"),
            confirmed_constraints=("stay in agent-context",),
            current_plan=("add compaction module", "add tests"),
            modified_files=("packages/agent-context/src/agent_context/compaction.py",),
            failed_attempts=("initial truncation was too aggressive",),
            unresolved_tests=("none",),
            approvals=("not required",),
            artifact_refs=("artifact://diff/123",),
            max_tokens=200,
        )
    )

    assert item.kind is ContextItemKind.CONVERSATION_SUMMARY
    assert "User Goal:" in item.content
    assert "Acceptance:" in item.content
    assert "Modified Files:" in item.content
    assert "Artifacts:" in item.content


def test_compact_tool_outputs_summarizes_multiple_evidences() -> None:
    item = compact_tool_outputs(
        ToolOutputCompactionRequest(
            evidences=(
                ToolOutputEvidence(
                    tool_name="tests.run",
                    output="2 passed\n0 failed",
                    artifact_uri="artifact://tests/1",
                ),
                ToolOutputEvidence(
                    tool_name="ruff.check",
                    output="All checks passed!",
                ),
            ),
            max_tokens=120,
        )
    )

    assert item.kind is ContextItemKind.TOOL_OUTPUT_SUMMARY
    assert "tests.run" in item.content
    assert "artifact://tests/1" in item.content
    assert "ruff.check" in item.content


def test_compaction_truncates_when_budget_is_small() -> None:
    item = compact_conversation(
        ConversationCompactionRequest(
            user_goal="x" * 400,
            current_plan=("y" * 400,),
            max_tokens=20,
        )
    )

    assert item.token_count <= 20
    assert item.content.endswith("...")
