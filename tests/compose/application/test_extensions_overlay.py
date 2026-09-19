"""Verify actual Compose merging without starting services or reading user env files."""

import json
import os
import re
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[3]
BASE = ROOT / "docker/compose.application.yml"
OVERLAY = ROOT / "docker/compose.extensions.yml"


def render(*, overlay=True, keys=True):
    if not shutil.which("docker"):
        pytest.skip("Docker Compose CLI unavailable")
    env = {k: v for k, v in os.environ.items() if not k.startswith(("ZEBRA_", "TRENCH_"))}
    env.update({key: "fixture" for key in re.findall(r"\$\{([A-Z0-9_]+):\?", BASE.read_text())})
    if keys:
        env.update({
            "ZEBRA_MCP_SECRET_HOST_ROOT": "/tmp/zebra-extension-fixture",
            "ZEBRA_MCP_KEY_HANDLE": "mcp/master",
            "ZEBRA_MCP_KEY_VERSION": "v1",
        })
    command = ["docker", "compose", "--env-file", "/dev/null", "-f", str(BASE)]
    if overlay:
        command += ["-f", str(OVERLAY)]
    return subprocess.run(
        [*command, "config", "--format", "json"], env=env, capture_output=True,
        text=True, timeout=20, check=False,
    )


def test_extension_overlay_pairs_api_worker_and_private_key_mounts():
    result = render()
    assert result.returncode == 0, result.stderr
    services = json.loads(result.stdout)["services"]
    for name in ("zebra-api", "zebra-worker"):
        service = services[name]
        assert service["environment"]["ZEBRA_CLOUD_MCP_WORKER_ENABLED"] == "true"
        mount = next(v for v in service["volumes"] if v["target"] == "/run/zebra-mcp-secrets")
        assert mount["read_only"] is True
        assert mount["bind"]["create_host_path"] is False
        assert mount["source"] == "/tmp/zebra-extension-fixture"
    assert not any(
        v["target"] == "/var/run/docker.sock" for v in services["zebra-api"]["volumes"]
    )
    assert any(
        v["target"] == "/var/run/docker.sock" for v in services["zebra-worker"]["volumes"]
    )
    assert "DOCKER_HOST" not in services["zebra-api"]["environment"]
    assert "DOCKER_HOST" in services["zebra-worker"]["environment"]
    api_env = services["zebra-api"]["environment"]
    worker_env = services["zebra-worker"]["environment"]
    assert api_env["ZEBRA_CLOUD_EXTENSION_TURN_ADMISSION_ENABLED"] == "true"
    assert worker_env["ZEBRA_CLOUD_EXTENSION_WORKER_ENABLED"] == "true"
    scheduler_env = services["zebra-scheduler"]["environment"]
    assert scheduler_env["ZEBRA_CLOUD_EXTENSIONS_READ_ENABLED"] == "true"
    assert scheduler_env["ZEBRA_CLOUD_EXTENSION_TURN_ADMISSION_ENABLED"] == "true"
    assert scheduler_env["ZEBRA_CLOUD_MCP_WORKER_ENABLED"] == "true"
    assert "ZEBRA_MCP_SECRET_ROOT" not in scheduler_env
    assert "ZEBRA_MCP_SECRET_ROOT" not in services["zebra-migrate"]["environment"]


def test_extension_overlay_requires_operator_key_configuration():
    assert render(keys=False).returncode != 0


def test_base_compose_does_not_silently_enable_extensions():
    result = render(overlay=False, keys=False)
    assert result.returncode == 0, result.stderr
    for service in json.loads(result.stdout)["services"].values():
        assert "ZEBRA_CLOUD_MCP_WORKER_ENABLED" not in service.get("environment", {})
