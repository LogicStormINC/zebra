"""Client Integration Plane must survive the production Compose boundary."""

import json
import os
import re
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[3]
COMPOSE = ROOT / "docker/compose.application.yml"


def _render() -> dict[str, object]:
    if not shutil.which("docker"):
        pytest.skip("Docker Compose CLI unavailable")
    env = {key: value for key, value in os.environ.items() if not key.startswith("ZEBRA_")}
    env.update({key: "fixture" for key in re.findall(r"\$\{([A-Z0-9_]+):\?", COMPOSE.read_text())})
    env.update(
        {
            "ZEBRA_CLIENT_INTEGRATION_ENABLED": "true",
            "ZEBRA_PLATFORM_OPERATOR_TOKEN": "operator-fixture",
            "ZEBRA_API_SSL_CERT_FILE": "/run/zebra/acceptance-bundle.pem",
            "ZEBRA_WORKER_SSL_CERT_FILE": "/run/zebra/acceptance-bundle.pem",
            "ZEBRA_DOCKER_SOCKET_GID": "0",
        }
    )
    result = subprocess.run(
        [
            "docker",
            "compose",
            "--env-file",
            "/dev/null",
            "-f",
            str(COMPOSE),
            "config",
            "--format",
            "json",
        ],
        env=env,
        capture_output=True,
        text=True,
        timeout=20,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    return json.loads(result.stdout)["services"]


def test_client_runtime_reaches_api_and_worker_without_leaking_operator_token() -> None:
    services = _render()
    api = services["zebra-api"]["environment"]
    worker = services["zebra-worker"]["environment"]
    assert api["ZEBRA_CLIENT_INTEGRATION_ENABLED"] == "true"
    assert worker["ZEBRA_CLIENT_INTEGRATION_ENABLED"] == "true"
    assert api["ZEBRA_PLATFORM_OPERATOR_TOKEN"] == "operator-fixture"
    assert "ZEBRA_PLATFORM_OPERATOR_TOKEN" not in worker
    assert "ZEBRA_PLATFORM_OPERATOR_TOKEN" not in services["zebra-migrate"]["environment"]
    assert api["SSL_CERT_FILE"] == "/run/zebra/acceptance-bundle.pem"
    assert worker["SSL_CERT_FILE"] == "/run/zebra/acceptance-bundle.pem"
    healthcheck = services["zebra-worker"]["healthcheck"]["test"]
    assert "docker version" in " ".join(healthcheck)
    assert "api_key_env" in " ".join(healthcheck)
