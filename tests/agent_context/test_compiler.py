from pathlib import Path

from agent_context import ContextBudget, ContextCompileRequest, ContextItemKind, compile_context


def test_compile_context_returns_ranked_items_with_provenance(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    (workspace / "AGENTS.md").write_text("Repository rules for editing.\n", encoding="utf-8")
    (workspace / "README.md").write_text("Project overview and setup.\n", encoding="utf-8")
    (workspace / "docs").mkdir()
    (workspace / "docs" / "runbook.md").write_text(
        "Run the smoke tests before merge.\n",
        encoding="utf-8",
    )
    (workspace / "src").mkdir()
    (workspace / "src" / "worker.py").write_text(
        "def run_worker() -> None:\n    pass\n",
        encoding="utf-8",
    )

    compiled = compile_context(
        ContextCompileRequest(
            task_input="inspect worker and repository rules",
            workspace_root=workspace.resolve(),
            budget=ContextBudget(max_tokens=200),
        )
    )

    assert compiled.items
    assert compiled.items[0].kind is ContextItemKind.REPO_MAP
    assert compiled.items[1].provenance.locator.endswith("AGENTS.md")
    assert compiled.items[1].priority >= compiled.items[-1].priority
    assert compiled.total_tokens <= 200


def test_compile_context_truncates_to_token_budget(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    (workspace / "README.md").write_text("overview " * 80, encoding="utf-8")
    (workspace / "module.py").write_text("print('hello')\n" * 40, encoding="utf-8")

    compiled = compile_context(
        ContextCompileRequest(
            task_input="read overview",
            workspace_root=workspace.resolve(),
            budget=ContextBudget(max_tokens=40),
        )
    )

    assert compiled.items
    assert compiled.total_tokens <= 40
    assert compiled.truncated is True
