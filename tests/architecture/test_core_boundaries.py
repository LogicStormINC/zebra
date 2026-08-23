"""Architecture gate: agent-core stays the dependency-free core.

AGENTS.md and ADR-021 forbid ``agent-core`` from importing any other
``agent-*`` package or the ``apps/`` composition roots. The historical
leak this gate guards against was
``agent_core.domain.orchestrator_definition`` importing
``agent_tools.contracts`` (an undeclared reverse dependency, closed by
the agent-orchestration extraction).
"""

from __future__ import annotations

import ast
import sys
from pathlib import Path
from tomllib import loads

PACKAGE_ROOT = Path(__file__).parents[2] / "packages" / "agent-core" / "src"
PYPROJECT = PACKAGE_ROOT.parent / "pyproject.toml"

ALLOWED_IMPORT_ROOTS = frozenset(sys.stdlib_module_names) | {
    "__future__",
    "agent_core",
    "pydantic",
}


def _import_roots(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    roots: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            roots.update(alias.name.partition(".")[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
            roots.add(node.module.partition(".")[0])
    return roots


def _python_sources() -> list[Path]:
    return sorted(path for path in PACKAGE_ROOT.rglob("*.py") if path.is_file())


def test_core_imports_only_stdlib_pydantic_and_itself() -> None:
    violations: list[str] = []
    for source in _python_sources():
        for root in sorted(_import_roots(source) - ALLOWED_IMPORT_ROOTS):
            violations.append(f"{source.relative_to(PACKAGE_ROOT)} -> {root}")
    assert not violations, f"agent-core boundary violations: {violations}"


def test_core_gate_catches_future_agent_package_and_bare_apps(tmp_path: Path) -> None:
    source = tmp_path / "leak.py"
    source.write_text(
        "from agent_future import Feature\nfrom apps import composition\n",
        encoding="utf-8",
    )
    assert _import_roots(source) - ALLOWED_IMPORT_ROOTS == {"agent_future", "apps"}


def test_core_declares_only_pydantic_dependency() -> None:
    project = loads(PYPROJECT.read_text(encoding="utf-8"))
    assert project["project"]["dependencies"] == ["pydantic>=2.11.7,<3.0.0"]
    assert project.get("tool", {}).get("uv", {}).get("sources", {}) == {}
