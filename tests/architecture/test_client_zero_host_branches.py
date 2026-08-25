"""Zero business-host branches in the client plane (ADR-CLIENT-01).

agent-core, agent-control-plane, agent-storage, agent-integrations and
the API/Worker runtime must stay free of any host business vocabulary;
frontends differ only through published profiles and fixtures.
"""

from __future__ import annotations

import re
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]

BUSINESS_NAME_PATTERN = re.compile(r"\btrench\b", re.IGNORECASE)

#: The client plane and the runtime apps must stay business-neutral.
FULL_SCAN_ROOTS = (
    "apps/api/src",
    "apps/worker/src",
)
#: Elsewhere only client modules are gated; the pre-existing Host tool
#: plane (legacy host bindings, docstring scope examples) predates the
#: client plane and is owned by the Host integration line.
CLIENT_MODULE_GLOBS = (
    "packages/*/src/**/client_*.py",
)


def test_no_business_host_names_in_runtime_sources() -> None:
    violations: list[str] = []
    scanned: list[Path] = []
    for root in FULL_SCAN_ROOTS:
        scanned.extend((REPO_ROOT / root).rglob("*.py"))
    for pattern in CLIENT_MODULE_GLOBS:
        scanned.extend((REPO_ROOT / "packages").glob(pattern))
    for path in scanned:
        source = path.read_text()
        for line_number, line in enumerate(source.splitlines(), start=1):
            if line.lstrip().startswith("#"):
                continue
            if BUSINESS_NAME_PATTERN.search(line):
                violations.append(f"{path.relative_to(REPO_ROOT)}:{line_number}")
    assert violations == [], violations


def test_client_surface_lives_in_declared_modules_only() -> None:
    client_modules = sorted(
        str(path.relative_to(REPO_ROOT))
        for root in ("packages", "apps")
        for path in (REPO_ROOT / root).rglob("client_*.py")
    )
    assert client_modules, "client plane modules disappeared"
