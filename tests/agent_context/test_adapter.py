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


def test_continuity_evidence_is_prioritized_and_not_cut_to_legacy_2000_chars(
    tmp_path: Path,
) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    late_marker = "LATE_HANDOFF_VALIDATION_MARKER"
    details = tuple(f"Touched file: path/to/file-{index}.py" for index in range(90)) + (
        f"Validation: {late_marker}",
    )

    prompt = LocalContextCompiler().build_system_prompt(
        task_input="continue the verified handoff",
        workspace_root=workspace.resolve(),
        max_tokens=1_600,
        confirmed_memories=tuple(
            ConfirmedMemoryInput(
                memory_type=MemoryType.PROJECT_RULE,
                text=f"Background memory {index} " + "x" * 120,
            )
            for index in range(8)
        ),
        runtime_evidence=(
            RuntimeEvidenceInput(
                kind="session_handoff",
                summary="Preserve the complete bounded continuity envelope.",
                details=details,
                metadata={"handoff_id": "handoff-rich"},
            ),
        ),
    )

    assert prompt is not None
    assert "Session Handoff Evidence" in prompt
    assert late_marker in prompt


def test_continuity_truncation_is_explicit_instead_of_silent(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()

    prompt = LocalContextCompiler().build_system_prompt(
        task_input="continue from a bounded handoff",
        workspace_root=workspace.resolve(),
        max_tokens=1_200,
        runtime_evidence=(
            RuntimeEvidenceInput(
                kind="session_handoff",
                summary="Large but bounded continuity envelope.",
                details=tuple("Touched file: " + "x" * 120 for _ in range(80)),
                metadata={"handoff_id": "handoff-large"},
            ),
        ),
    )

    assert prompt is not None
    assert "Known omission: continuity_evidence_truncated" in prompt


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
