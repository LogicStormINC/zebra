"""Pin the least-privilege Schedule runtime composition."""

import json
import os
import re
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[3]
BASE = ROOT / "docker/compose.application.yml"
ACCEPTANCE = ROOT / "docker/compose.trench-acceptance.yml"


def _render(path: Path) -> dict[str, object]:
    if not shutil.which("docker"):
        pytest.skip("Docker Compose CLI unavailable")
    env = {key: value for key, value in os.environ.items() if not key.startswith("ZEBRA_")}
    env.update({key: "fixture" for key in re.findall(r"\$\{([A-Z0-9_]+):\?", path.read_text())})
    result = subprocess.run(
        ["docker", "compose", "--env-file", "/dev/null", "-f", str(path),
         "config", "--format", "json"],
        env=env, capture_output=True, text=True, timeout=20, check=False,
    )
    assert result.returncode == 0, result.stderr
    return json.loads(result.stdout)


def test_scheduler_is_independent_and_only_it_receives_workload_secret() -> None:
    services = _render(BASE)["services"]
    scheduler = services["zebra-scheduler"]

    assert scheduler["build"]["target"] == "scheduler"
    assert scheduler["depends_on"]["zebra-migrate"]["condition"] == "service_completed_successfully"
    assert scheduler["read_only"] is True
    assert scheduler["environment"]["ZEBRA_SCHEDULER_WORKLOAD_SHARED_SECRET"] == "fixture"
    for name in ("zebra-api", "zebra-worker", "zebra-migrate"):
        assert "ZEBRA_SCHEDULER_WORKLOAD_SHARED_SECRET" not in services[name]["environment"]


def test_trench_broker_default_admits_schedule_scope_and_identity() -> None:
    environment = _render(ACCEPTANCE)["services"]["trench-grant-broker"]["environment"]

    assert {"schedule.read", "schedule.manage"} <= set(
        environment["ZEBRA_GRANT_BROKER_ALLOWED_SCOPES"].split(",")
    )
    assert "trench-scheduler" in environment["ZEBRA_GRANT_BROKER_WORKLOAD_IDENTITIES"].split(",")
