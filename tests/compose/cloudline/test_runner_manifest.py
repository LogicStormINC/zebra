from __future__ import annotations

import json
from pathlib import Path
from typing import cast

ROOT = Path(__file__).parents[3]
MANIFEST = Path(__file__).with_name("runner_manifest.json")
WORKFLOW = ROOT / ".github/workflows/quality.yml"
EXPECTED_RUNNERS = {
    "application",
    "live-fanout",
    "recovery-pitr",
    "recovery-s3",
    "recovery-restore",
}


def _document() -> dict[str, object]:
    return cast(dict[str, object], json.loads(MANIFEST.read_text(encoding="utf-8")))


def test_manifest_has_bounded_distinct_runners_and_real_scripts() -> None:
    document = _document()
    assert document["schema_version"] == "zebra.cloudline.runner-manifest.v1"
    runners = document["runners"]
    assert isinstance(runners, list)
    assert {runner["id"] for runner in runners} == EXPECTED_RUNNERS
    assert len(runners) == len(EXPECTED_RUNNERS)
    for runner in runners:
        script = ROOT / runner["script"]
        assert script.is_file(), runner["id"]
        assert script.stat().st_mode & 0o111, runner["id"]
        assert runner["timeout_seconds"] > 0


def test_quality_workflow_runs_and_retains_every_runner() -> None:
    workflow = WORKFLOW.read_text(encoding="utf-8")
    assert "real-services:" in workflow
    assert "fail-fast: false" in workflow
    assert "timeout-minutes:" in workflow
    assert "actions/upload-artifact@" in workflow
    assert "if: always()" in workflow
    assert "continue-on-error" not in workflow
    for runner_id in EXPECTED_RUNNERS:
        assert f'"{runner_id}"' in workflow
    assert "run_real_service.py" in workflow
