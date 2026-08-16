"""ARCH-129-CTX-01: bounded code intelligence index tests."""

from __future__ import annotations

from pathlib import Path

import pytest
from agent_context.code_intelligence import (
    DEFAULT_MAX_RESULTS,
    CodeIntelligenceIndex,
)


@pytest.fixture
def workspace(tmp_path: Path) -> Path:
    (tmp_path / "app.py").write_text(
        "def alpha():\n"
        "    return 1\n"
        "\n"
        "\n"
        "class Beta:\n"
        "    def method(self):\n"
        "        return alpha()\n",
        encoding="utf-8",
    )
    (tmp_path / "lib.ts").write_text(
        "function gamma(): number {\n"
        "  return 42;\n"
        "}\n"
        "\n"
        "const caller = gamma;\n",
        encoding="utf-8",
    )
    (tmp_path / "notes.md").write_text("# not code\n", encoding="utf-8")
    return tmp_path


def test_definitions_carry_provenance(workspace: Path) -> None:
    index = CodeIntelligenceIndex(workspace).build()
    alpha = index.definitions("alpha")
    assert len(alpha) == 1
    assert alpha[0].range.file == "app.py"
    assert alpha[0].range.line == 1
    assert alpha[0].kind == "function"
    beta = index.definitions("Beta")
    assert beta[0].kind == "type"


def test_references_are_bounded_lexical_hints(workspace: Path) -> None:
    index = CodeIntelligenceIndex(workspace).build()
    refs = index.references("alpha")
    files = {ref.range.file for ref in refs}
    assert "app.py" in files
    assert all(ref.name == "alpha" for ref in refs)


def test_search_prefix_and_ceilings(workspace: Path) -> None:
    index = CodeIntelligenceIndex(workspace, max_results=1).build()
    results = index.search("a")
    assert 1 <= len(results) <= DEFAULT_MAX_RESULTS
    stats = index.stats()
    assert stats["files_indexed"] == 3  # all files scanned; markdown yields no symbols
    assert stats["symbols"] == 4  # alpha, Beta, method, gamma
    assert stats["max_results"] == 1


def test_file_ceilings_are_enforced(tmp_path: Path) -> None:
    (tmp_path / "big.py").write_text("def visible():\n    pass\n" + "x = 1\n" * 100)
    (tmp_path / "small.py").write_text("def hidden():\n    pass\n")
    index = CodeIntelligenceIndex(tmp_path, max_files=1).build()
    assert index.stats()["files_indexed"] == 1
    assert index.definitions("visible") or index.definitions("hidden")


def test_nonexistent_root_fails_closed(tmp_path: Path) -> None:
    with pytest.raises(ValueError):
        CodeIntelligenceIndex(tmp_path / "missing").build()
