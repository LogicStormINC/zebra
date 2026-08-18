"""Architecture gate: the cloud API surface stays decoupled from execution.

AL-API-BOUNDARY-01: `apps/api` modules must not import `zebra_agent_worker`
or `agent_runtime` execution directly; the local-profile inline path goes
through the single `zebra_agent_api.local_execution` seam (and the eventual
goal of AL-API-DECOUPLE-01 is dropping even that from the cloud artifact).
"""

from __future__ import annotations

import re
from pathlib import Path

API_SRC = Path(__file__).parents[2] / "apps" / "api" / "src" / "zebra_agent_api"
SEAM_MODULE = "local_execution.py"
WORKER_IMPORT = re.compile(r"^\s*(from|import)\s+zebra_agent_worker\b", re.MULTILINE)
RUNTIME_EXECUTION_IMPORT = re.compile(
    r"^\s*from agent_runtime import.*run_local_harness", re.MULTILINE
)


def _modules() -> list[Path]:
    return sorted(path for path in API_SRC.rglob("*.py") if path.is_file())


def test_only_the_local_seam_imports_execution_packages() -> None:
    violations: list[str] = []
    for module in _modules():
        if module.name == SEAM_MODULE:
            continue
        text = module.read_text(encoding="utf-8")
        if WORKER_IMPORT.search(text) or RUNTIME_EXECUTION_IMPORT.search(text):
            violations.append(str(module.relative_to(API_SRC)))
    assert not violations, f"API modules bypass the local execution seam: {violations}"


def test_the_seam_exists_and_is_bounded() -> None:
    seam = API_SRC / SEAM_MODULE
    assert seam.is_file(), "local execution seam module is missing"
    text = seam.read_text(encoding="utf-8")
    assert "run_local_harness" in text
    assert "SessionExecutionService" in text


def test_execution_packages_are_local_extras_only() -> None:
    pyproject = API_SRC.parents[1] / "pyproject.toml"
    text = pyproject.read_text(encoding="utf-8")
    dependencies = text.split("dependencies = [", 1)[1].split("]", 1)[0]
    for forbidden in ("agent-runtime", "zebra-agent-worker"):
        assert forbidden not in dependencies, f"{forbidden} must be a local extra"
    extras = text.split("[project.optional-dependencies]", 1)[1]
    assert "local = [" in extras
    assert '"agent-runtime"' in extras
    assert '"zebra-agent-worker"' in extras


def test_seam_is_imported_lazily_outside_local_paths() -> None:
    for module in _modules():
        if module.name == SEAM_MODULE:
            continue
        text = module.read_text(encoding="utf-8")
        if "from zebra_agent_api.local_execution import" in text:
            # allowed only as a function-level (indented) import
            for line in text.splitlines():
                if "from zebra_agent_api.local_execution import" in line and not line.startswith(
                    " "
                ):
                    raise AssertionError(
                        f"{module.relative_to(API_SRC)} imports the seam at module level"
                    )
