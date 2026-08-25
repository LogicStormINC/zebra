"""Architecture boundaries for the platform control-plane bundle.

The bundle port stays core-pure; the storage composition may not import
apps; the API/worker composition modules may not construct stores of
their own beyond the shared bundle.
"""

from __future__ import annotations

import ast
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]


def _import_roots(path: Path) -> set[str]:
    tree = ast.parse(path.read_text())
    roots: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            roots.update(alias.name.split(".")[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            roots.add(node.module.split(".")[0])
    return roots


ALLOWED_FOR_PORT = {
    "__future__",
    "dataclasses",
    "typing",
    "agent_core",
}


def test_platform_port_module_stays_core_pure() -> None:
    path = (
        REPO_ROOT
        / "packages/agent-core/src/agent_core/ports/platform_control_plane.py"
    )
    roots = _import_roots(path)
    assert roots <= ALLOWED_FOR_PORT, roots - ALLOWED_FOR_PORT


def test_storage_platform_composition_does_not_import_apps() -> None:
    path = (
        REPO_ROOT
        / "packages/agent-storage/src/agent_storage/postgres_platform_composition.py"
    )
    roots = _import_roots(path)
    assert "apps" not in roots
    assert "zebra_agent_api" not in roots
    assert "zebra_agent_worker" not in roots


def test_api_and_worker_composition_share_the_storage_bundle() -> None:
    api = (
        REPO_ROOT
        / "apps/api/src/zebra_agent_api/platform_composition.py"
    ).read_text()
    worker = (
        REPO_ROOT
        / "apps/worker/src/zebra_agent_worker/platform_composition.py"
    ).read_text()
    assert "postgres_agent_platform_control_plane" in api
    assert "postgres_agent_platform_control_plane" in worker
    # no business host names leak into the composition layer
    for source in (api, worker):
        assert "trench" not in source.lower()


def test_platform_composition_declares_no_business_hosts() -> None:
    source = (
        REPO_ROOT
        / "packages/agent-storage/src/agent_storage/postgres_platform_composition.py"
    ).read_text()
    assert "trench" not in source.lower()
