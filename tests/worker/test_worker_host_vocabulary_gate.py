"""Gate: Worker production code carries no Host-specific vocabulary.

AL-WORKER-GENERIC-01 / ADR-017 decision 6: adding a second Host must not
add Host-name branches to Worker production code. Host vocabulary lives in
manifest declarations, Host fixtures, and Host adapters under
``agent-integrations`` — never under ``apps/worker/src``.
"""

from __future__ import annotations

import re
from pathlib import Path

WORKER_SRC = Path(__file__).parents[2] / "apps" / "worker" / "src"

HOST_NAME_PATTERN = re.compile(r"\btrench\b|\bjazz\b|onelink", re.IGNORECASE)
LEGACY_TOOL_NAME_PATTERN = re.compile(r"events\.get_(event|evidence|related_events)")


def _production_sources() -> list[Path]:
    return sorted(path for path in WORKER_SRC.rglob("*.py") if path.is_file())


def test_worker_sources_have_no_host_names() -> None:
    violations: list[str] = []
    for source in _production_sources():
        text = source.read_text(encoding="utf-8")
        if HOST_NAME_PATTERN.search(text):
            violations.append(str(source.relative_to(WORKER_SRC)))
    assert not violations, f"Worker production code mentions Host names: {violations}"


def test_worker_sources_have_no_host_tool_name_branches() -> None:
    violations: list[str] = []
    for source in _production_sources():
        text = source.read_text(encoding="utf-8")
        if LEGACY_TOOL_NAME_PATTERN.search(text):
            violations.append(str(source.relative_to(WORKER_SRC)))
    assert not violations, f"Worker production code branches on Host tool names: {violations}"
