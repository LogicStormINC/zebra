from pathlib import Path

from agent_context import LocalContextCompiler
from agent_core.domain.memories import MemoryType
from agent_core.ports.context_compiler import ConfirmedMemoryInput, RuntimeEvidenceInput


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


def test_local_context_compiler_renders_untrusted_session_handoff_evidence(
    tmp_path: Path,
) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()

    prompt = LocalContextCompiler().build_system_prompt(
        task_input="continue the next stage",
        workspace_root=workspace.resolve(),
        max_tokens=160,
        runtime_evidence=(
            RuntimeEvidenceInput(
                kind="session_handoff",
                summary="Preserve continuity marker ZEBRA-HANDOFF-1234.",
                details=("Completed: parent provider call completed",),
                metadata={"handoff_id": "handoff-1234"},
            ),
        ),
    )

    assert prompt is not None
    assert "Dynamic Context:" in prompt
    assert "Session Handoff Evidence" in prompt
    assert "Untrusted session handoff evidence" in prompt
    assert "ZEBRA-HANDOFF-1234" in prompt
    assert "parent provider call completed" in prompt


def test_local_context_compiler_keeps_checkpoint_handoffs_bounded(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    checkpoint_tail = "CHECKPOINT-TAIL-MUST-NOT-REACH-THE-MODEL"

    prompt = LocalContextCompiler().build_system_prompt(
        task_input="continue the checkpoint handoff",
        workspace_root=workspace.resolve(),
        max_tokens=800,
        runtime_evidence=(
            RuntimeEvidenceInput(
                kind="session_handoff",
                summary="Continue the prior checkpoint.",
                details=("Completed: " + "x" * 2_100 + checkpoint_tail,),
                metadata={"handoff_source": "checkpoint"},
            ),
        ),
    )

    assert prompt is not None
    assert "Completed:" in prompt
    assert checkpoint_tail not in prompt


def test_local_context_compiler_renders_confirmed_memory_in_stable_section(
    tmp_path: Path,
) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    (workspace / "README.md").write_text("Project overview.\n", encoding="utf-8")

    prompt = LocalContextCompiler().build_system_prompt(
        task_input="inspect confirmed memory",
        workspace_root=workspace.resolve(),
        max_tokens=160,
        confirmed_memories=(
            ConfirmedMemoryInput(
                memory_type=MemoryType.PROJECT_RULE,
                text="This repo uses uv instead of Poetry.",
            ),
            ConfirmedMemoryInput(
                memory_type=MemoryType.PROCEDURE,
                text="Run make check before push.",
            ),
        ),
    )

    assert prompt is not None
    assert "Stable Context:" in prompt
    assert "Project Rule 1" in prompt
    assert "Procedure 2" in prompt
    assert "This repo uses uv instead of Poetry." in prompt
    assert "Run make check before push." in prompt
