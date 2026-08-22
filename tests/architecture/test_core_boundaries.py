"""Architecture gate: agent-core stays the dependency-free core.

AGENTS.md and ADR-021 forbid ``agent-core`` from importing any other
``agent-*`` package or the ``apps/`` composition roots. The historical
leak this gate guards against was
``agent_core.domain.orchestrator_definition`` importing
``agent_tools.contracts`` (an undeclared reverse dependency, closed by
the agent-orchestration extraction).
"""

from __future__ import annotations

from pathlib import Path

PACKAGE_ROOT = Path(__file__).parents[2] / "packages" / "agent-core" / "src"

FORBIDDEN_TOKENS = (
    "agent_tools",
    "agent_orchestration",
    "agent_control_plane",
    "agent_storage",
    "agent_integrations",
    "agent_runtime",
    "agent_security",
    "agent_context",
    "agent_observability",
    "zebra_agent_worker",
    "fastapi",
    "apps.",
)


def _python_sources() -> list[Path]:
    return sorted(path for path in PACKAGE_ROOT.rglob("*.py") if path.is_file())


def test_core_never_imports_other_agent_packages_or_apps() -> None:
    violations: list[str] = []
    for source in _python_sources():
        text = source.read_text(encoding="utf-8")
        for token in FORBIDDEN_TOKENS:
            if f"import {token}" in text or f"from {token}" in text:
                violations.append(f"{source.relative_to(PACKAGE_ROOT)} -> {token}")
    assert not violations, f"agent-core boundary violations: {violations}"
