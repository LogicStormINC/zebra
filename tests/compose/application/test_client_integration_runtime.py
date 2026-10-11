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


def _render(platform: str | None = None, *, local_gvisor: bool = False) -> dict[str, object]:
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
    if platform is not None:
        env["ZEBRA_APPLICATION_PLATFORM"] = platform
    if local_gvisor:
        env.update({"ZEBRA_LOCAL_GVISOR_ADDRESS": "192.0.2.10",
                    "ZEBRA_LOCAL_GVISOR_CERT_GID": "20",
                    "ZEBRA_WORKSPACE_VOLUME_ROOT": "/quota/zebra"})
    result = subprocess.run(
        [
            "docker",
            "compose",
            "--env-file",
            "/dev/null",
            "-f",
            str(COMPOSE),
            *(["-f", str(ROOT / "docker/compose.local-gvisor.yml")] if local_gvisor else []),
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


def test_local_gvisor_uses_authenticated_engine_without_local_socket_or_data_migration():
    services = _render(local_gvisor=True)
    worker = services["zebra-worker"]
    assert worker["environment"]["DOCKER_HOST"] == "tcp://192.0.2.10:2376"
    assert worker["environment"]["DOCKER_TLS_VERIFY"] == "1"
    assert worker["environment"]["DOCKER_CERT_PATH"] == "/run/zebra-engine-tls"
    mounts = {mount["target"]: mount for mount in worker["volumes"]}
    assert "/var/run/docker.sock" not in mounts
    assert mounts["/run/zebra-engine-tls"]["read_only"] is True
    assert mounts["/quota/zebra"]["source"] == "/quota/zebra"
    assert "20" in worker["group_add"]
    assert "DOCKER_TLS_VERIFY" not in services["zebra-api"]["environment"]
    assert services["zebra-api"]["networks"] == services["zebra-worker"]["networks"]


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
    assert "zebra_agent_worker.runtime_preflight" in " ".join(healthcheck)
    assert "api_key_env" in " ".join(healthcheck)


@pytest.mark.parametrize("platform", [None, "linux/arm64", "linux/amd64"])
def test_application_platform_is_explicit_and_shared_by_execution_services(platform):
    services = _render(platform)
    for service in ("zebra-migrate", "zebra-api", "zebra-worker"):
        assert services[service]["platform"] == (platform or "linux/amd64")
