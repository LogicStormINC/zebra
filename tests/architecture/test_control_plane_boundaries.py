"""Architecture gate: the Agent Control Plane stays a pure application layer.

AL-BOUNDARY-CON-01 / ADR-017 forbid the control plane from importing the
Worker, the Runtime, HTTP frameworks, or storage adapters. ADR-021 adds
that it never imports ``agent-orchestration`` either: the allowed
direction is orchestration → control plane, never the reverse.
"""

from __future__ import annotations

from pathlib import Path

PACKAGE_ROOT = Path(__file__).parents[2] / "packages" / "agent-control-plane" / "src"

FORBIDDEN_TOKENS = (
    "zebra_agent_worker",
    "agent_runtime",
    "fastapi",
    "uvicorn",
    "agent_storage",
    "agent_orchestration",
    "apps.",
)


def _python_sources() -> list[Path]:
    return sorted(path for path in PACKAGE_ROOT.rglob("*.py") if path.is_file())


def test_package_exists_with_sources() -> None:
    sources = _python_sources()
    assert sources, "agent_control_plane package sources are missing"


def test_control_plane_never_imports_forbidden_layers() -> None:
    violations: list[str] = []
    for source in _python_sources():
        text = source.read_text(encoding="utf-8")
        for token in FORBIDDEN_TOKENS:
            if f"import {token}" in text or f"from {token}" in text:
                violations.append(f"{source.relative_to(PACKAGE_ROOT)} -> {token}")
    assert not violations, f"control-plane boundary violations: {violations}"


def test_control_plane_declares_only_core_dependency() -> None:
    pyproject = PACKAGE_ROOT.parent / "pyproject.toml"
    text = pyproject.read_text(encoding="utf-8")
    assert '"agent-core",' in text
    for forbidden in (
        "agent-runtime",
        "agent-storage",
        "zebra-agent-worker",
        "fastapi",
        "agent-orchestration",
    ):
        assert forbidden not in text, f"unexpected dependency: {forbidden}"
