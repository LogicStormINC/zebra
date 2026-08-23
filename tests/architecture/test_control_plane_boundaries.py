"""Architecture gate: the Agent Control Plane stays a pure application layer.

AL-BOUNDARY-CON-01 / ADR-017 forbid the control plane from importing the
Worker, the Runtime, HTTP frameworks, or storage adapters. ADR-021 adds
that it never imports ``agent-orchestration`` either: the allowed
direction is orchestration → control plane, never the reverse.
"""

from __future__ import annotations

import ast
import sys
from pathlib import Path
from tomllib import loads

PACKAGE_ROOT = Path(__file__).parents[2] / "packages" / "agent-control-plane" / "src"
PYPROJECT = PACKAGE_ROOT.parent / "pyproject.toml"

ALLOWED_IMPORT_ROOTS = frozenset(sys.stdlib_module_names) | {
    "__future__",
    "agent_control_plane",
    "agent_core",
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


def test_package_exists_with_sources() -> None:
    sources = _python_sources()
    assert sources, "agent_control_plane package sources are missing"


def test_control_plane_imports_only_stdlib_core_and_itself() -> None:
    violations: list[str] = []
    for source in _python_sources():
        for root in sorted(_import_roots(source) - ALLOWED_IMPORT_ROOTS):
            violations.append(f"{source.relative_to(PACKAGE_ROOT)} -> {root}")
    assert not violations, f"control-plane boundary violations: {violations}"


def test_control_plane_declares_only_core_dependency() -> None:
    project = loads(PYPROJECT.read_text(encoding="utf-8"))
    assert project["project"]["dependencies"] == ["agent-core"]
    assert project["tool"]["uv"]["sources"] == {"agent-core": {"workspace": True}}
