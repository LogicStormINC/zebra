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
PRO_TEST = ROOT / "docker/compose.coverage-pro-test.yml"


def _render(
    platform: str | None = None, *, local_gvisor: bool = False,
    coverage_pro: bool = False, compat: bool = False,
) -> dict[str, object]:
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
            "DEEPSEEK_API_KEY": "fixture-only",
        }
    )
    if platform is not None:
        env["ZEBRA_APPLICATION_PLATFORM"] = platform
    if local_gvisor:
        env.update({"ZEBRA_LOCAL_GVISOR_ADDRESS": "192.0.2.10",
                    "ZEBRA_LOCAL_GVISOR_CERT_GID": "20",
                    "ZEBRA_LOCAL_GVISOR_CLIENT_CERT_DIR": "/fixture/engine-certs",
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
            *(["-f", str(ROOT / "docker/compose.trench-compat.yml")] if compat else []),
            *(["-f", str(PRO_TEST)] if coverage_pro else []),
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


def test_coverage_pro_pairs_api_worker_model_and_aliases():
    services = _render("linux/arm64", local_gvisor=True, coverage_pro=True, compat=True)
    for name in ("zebra-api", "zebra-api-legacy", "zebra-worker"):
        env = services[name]["environment"]
        assert env["ZEBRA_MODEL_PROVIDER"] == "deepseek"
        assert env["ZEBRA_MODEL_NAME"] == env["DEEPSEEK_MODEL"] == "deepseek-v4-pro"
        assert env["ZEBRA_MODEL_BASE_URL"] == env["DEEPSEEK_BASE_URL"] == "https://api.deepseek.com"
        assert env["ZEBRA_DEEPSEEK_REVIEWER_PROFILE"] == "deepseek-v4-pro-reviewer-v1"
        assert env["ZEBRA_DEEPSEEK_WIRE_API"] == "chat_completions"


@pytest.mark.parametrize("local_gvisor", [False, True])
def test_coverage_pro_changes_only_model_settings_not_authority_or_runtime(local_gvisor):
    before = _render("linux/arm64", local_gvisor=local_gvisor, compat=True)
    after = _render("linux/arm64", local_gvisor=local_gvisor, coverage_pro=True, compat=True)
    changed = {
        "ZEBRA_MODEL_PROVIDER", "ZEBRA_MODEL_NAME", "DEEPSEEK_MODEL",
        "ZEBRA_MODEL_BASE_URL", "DEEPSEEK_BASE_URL", "ZEBRA_DEEPSEEK_REVIEWER_PROFILE",
        "ZEBRA_DEEPSEEK_WIRE_API",
    }
    for name in ("zebra-api", "zebra-api-legacy", "zebra-worker"):
        for key in changed:
            assert key not in before[name]["environment"]
            del after[name]["environment"][key]
    assert after == before


@pytest.mark.parametrize("local_gvisor", [False, True])
def test_compat_preserves_legacy_scheduler_and_private_tls(local_gvisor):
    services = _render(local_gvisor=local_gvisor, compat=True)
    assert services["zebra-api"]["depends_on"]["zebra-api-legacy"]["condition"] == "service_started"
    legacy = services["zebra-api-legacy"]
    assert legacy["environment"]["ZEBRA_DEPLOYMENT_NAMESPACE"] == "trench-prod"
    assert "build" not in legacy
    assert legacy["image"] == "zebra-application-zebra-api"
    scheduler = services["zebra-scheduler"]
    assert not scheduler.get("profiles")
    assert scheduler["environment"]["ZEBRA_SCHEDULER_ID"] == "trench-scheduler"
    assert scheduler["environment"]["ZEBRA_SCHEDULER_WORKLOAD_IDENTITY"] == "trench-scheduler"
    for name in ("zebra-api", "zebra-api-legacy", "zebra-worker", "zebra-scheduler"):
        mounts = {mount["target"]: mount for mount in services[name]["volumes"]}
        assert mounts["/etc/ssl/certs/zebra-local-unused.0"]["read_only"] is True
        if name != "zebra-scheduler":
            assert mounts["/etc/ssl/certs/zebra-acceptance-ca-bundle.crt"]["read_only"] is True
    if local_gvisor:
        mounts = {mount["target"] for mount in services["zebra-worker"]["volumes"]}
        assert "/run/zebra-engine-tls" in mounts
        assert "/var/run/docker.sock" not in mounts


def test_base_has_no_legacy_scheduler_or_private_ca_prerequisites():
    services = _render()
    assert set(services) == {"zebra-migrate", "zebra-api", "zebra-worker"}
    assert set(services["zebra-api"]["depends_on"]) == {"zebra-migrate"}
    for service in services.values():
        assert all("trench" not in mount["source"] for mount in service.get("volumes", []))
