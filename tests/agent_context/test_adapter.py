from pathlib import Path

from agent_context import LocalContextCompiler
from agent_core.ports.context_compiler import RuntimeEvidenceInput


def test_local_context_compiler_renders_system_prompt(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    (workspace / "AGENTS.md").write_text("Repository rules.\n", encoding="utf-8")
    (workspace / "README.md").write_text("Project overview.\n", encoding="utf-8")

    prompt = LocalContextCompiler().build_system_prompt(
        task_input="inspect repository rules",
        workspace_root=workspace.resolve(),
        max_tokens=120,
    )

    assert prompt is not None
    assert "Stable Context:" in prompt
    assert "Semi-Stable Context:" in prompt


def test_local_context_compiler_renders_runtime_evidence_in_dynamic_section(
    tmp_path: Path,
) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    (workspace / "AGENTS.md").write_text("Repository rules.\n", encoding="utf-8")

    prompt = LocalContextCompiler().build_system_prompt(
        task_input="inspect runtime evidence",
        workspace_root=workspace.resolve(),
        max_tokens=160,
        runtime_evidence=(
            RuntimeEvidenceInput(
                kind="conversation_summary",
                summary="Retry after test failure.",
                details=("inspect logs",),
            ),
            RuntimeEvidenceInput(
                kind="planner_summary",
                summary="Run targeted smoke tests.",
            ),
            RuntimeEvidenceInput(
                kind="verifier_summary",
                summary="Smoke tests are still failing.",
                metadata={"passed": False},
            ),
        ),
    )

    assert prompt is not None
    assert "Dynamic Context:" in prompt
    assert "Conversation Summary" in prompt
    assert "Run targeted smoke tests." in prompt
    assert "Smoke tests are still failing." in prompt
