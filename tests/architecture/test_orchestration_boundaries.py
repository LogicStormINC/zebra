"""Architecture gate: agent-orchestration stays a deterministic application package.

AL-BOUNDARY-ORCH-01 / ADR-021 freeze the Orchestration Control Plane
package: it owns plan/budget contracts, DAG validation and scheduling,
child-task materialization coordination, the completion gate and the
``system/orchestrator@1`` definition, and it never imports the Worker,
the Runtime, HTTP frameworks, storage adapters or provider integrations.
The dependency direction to the Agent Control Plane is one-way —
orchestration may call the control plane, never the reverse (that
direction is guarded in ``test_control_plane_boundaries.py``).
"""

from __future__ import annotations

import ast
import sys
from pathlib import Path
from tomllib import loads

PACKAGE_ROOT = Path(__file__).parents[2] / "packages" / "agent-orchestration" / "src"
PYPROJECT = PACKAGE_ROOT.parent / "pyproject.toml"

ALLOWED_IMPORT_ROOTS = frozenset(sys.stdlib_module_names) | {
    "__future__",
    "agent_core",
    "agent_orchestration",
    "agent_tools",
    "pydantic",
}
EXPECTED_DEPENDENCIES = {
    "agent-core==0.1.0",
    "agent-tools==0.1.0",
    "pydantic>=2.11.7,<3.0.0",
}
EXPECTED_WORKSPACE_SOURCES = {
    "agent-core": {"workspace": True},
    "agent-tools": {"workspace": True},
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
    assert sources, "agent_orchestration package sources are missing"


def test_orchestration_imports_only_boundary_modules() -> None:
    violations: list[str] = []
    for source in _python_sources():
        for root in sorted(_import_roots(source) - ALLOWED_IMPORT_ROOTS):
            violations.append(f"{source.relative_to(PACKAGE_ROOT)} -> {root}")
    assert not violations, f"orchestration boundary violations: {violations}"


def test_orchestration_gate_catches_foreign_packages(tmp_path: Path) -> None:
    source = tmp_path / "leak.py"
    source.write_text(
        "from agent_security import Policy\nimport httpx\n",
        encoding="utf-8",
    )
    assert _import_roots(source) - ALLOWED_IMPORT_ROOTS == {"agent_security", "httpx"}


def test_orchestration_declares_exact_dependencies() -> None:
    project = loads(PYPROJECT.read_text(encoding="utf-8"))
    assert set(project["project"]["dependencies"]) == EXPECTED_DEPENDENCIES
    assert project["tool"]["uv"]["sources"] == EXPECTED_WORKSPACE_SOURCES
