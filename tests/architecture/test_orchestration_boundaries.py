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

from pathlib import Path

PACKAGE_ROOT = Path(__file__).parents[2] / "packages" / "agent-orchestration" / "src"

FORBIDDEN_TOKENS = (
    "zebra_agent_worker",
    "agent_runtime",
    "fastapi",
    "uvicorn",
    "agent_storage",
    "agent_integrations",
    "apps.",
)


def _python_sources() -> list[Path]:
    return sorted(path for path in PACKAGE_ROOT.rglob("*.py") if path.is_file())


def test_package_exists_with_sources() -> None:
    sources = _python_sources()
    assert sources, "agent_orchestration package sources are missing"


def test_orchestration_never_imports_forbidden_layers() -> None:
    violations: list[str] = []
    for source in _python_sources():
        text = source.read_text(encoding="utf-8")
        for token in FORBIDDEN_TOKENS:
            if f"import {token}" in text or f"from {token}" in text:
                violations.append(f"{source.relative_to(PACKAGE_ROOT)} -> {token}")
    assert not violations, f"orchestration boundary violations: {violations}"


def test_orchestration_declares_only_core_and_tools_dependencies() -> None:
    pyproject = PACKAGE_ROOT.parent / "pyproject.toml"
    text = pyproject.read_text(encoding="utf-8")
    assert '"agent-core",' in text
    assert '"agent-tools",' in text
    for forbidden in (
        "agent-runtime",
        "agent-storage",
        "agent-integrations",
        "zebra-agent-worker",
        "fastapi",
    ):
        assert forbidden not in text, f"unexpected dependency: {forbidden}"
