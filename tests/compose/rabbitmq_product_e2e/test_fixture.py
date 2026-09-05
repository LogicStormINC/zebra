"""No-service-start checks for isolation and secret handling."""

import importlib.util
import re
import subprocess
from pathlib import Path

import pytest

HERE = Path(__file__).parent
spec = importlib.util.spec_from_file_location("product_fixture", HERE / "fixture.py")
assert spec and spec.loader
fixture = importlib.util.module_from_spec(spec)
spec.loader.exec_module(fixture)


@pytest.fixture
def environment(monkeypatch, tmp_path):
    for name in ("ca.crt", "tls.crt", "tls.key", "trench-host-grant-v1.pem"):
        (tmp_path / name).touch()
    monkeypatch.setattr(fixture, "SECRETS", tmp_path)
    monkeypatch.setattr(
        fixture,
        "captured",
        lambda args: "1234abcd" if args[0] == "openssl" else "sha256:" + "1" * 64,
    )
    return fixture.build_environment(
        {
            "DEEPSEEK_API_KEY": "sentinel-never-log",
            "ZEBRA_RUNTIME_IMAGE": "sandbox@sha256:" + "2" * 64,
            "ZEBRA_DATABASE_URL": "postgresql://production:secret@original/db",
            "ZEBRA_HOST_TOOL_SHARED_SECRET": "original-workload-secret",
        }
    )


def test_synthetic_targets_and_no_reused_authority(environment):
    env = environment
    assert "@postgres:5432/zebra_e2e" in env["ZEBRA_DATABASE_URL"]
    assert "@127.0.0.1:28432/trench_e2e" in env["E2E_TRENCH_HOST_DSN"]
    assert env["E2E_WORKLOAD_SECRET"] != "original-workload-secret"
    assert "production" not in env["ZEBRA_DATABASE_URL"]
    assert env["E2E_WORKSPACE_ROOT"] == str(fixture.WORKSPACE)


@pytest.mark.parametrize("path", ["/", "/Volumes/ZEBRATRENCH", "/tmp/rabbitmq-product-e2e"])
def test_original_or_broad_workspace_forbidden(path):
    with pytest.raises(ValueError):
        fixture.validate_workspace(Path(path))


def test_workspace_symlink_rejected(monkeypatch, tmp_path):
    child = tmp_path / "rabbitmq-product-e2e"
    child.symlink_to(tmp_path, target_is_directory=True)
    monkeypatch.setattr(fixture, "WORKSPACE", child)
    with pytest.raises(ValueError):
        fixture.validate_workspace(child)


@pytest.mark.parametrize(
    "key,value",
    [
        ("ZEBRA_DATABASE_URL", "postgresql://original/prod"),
        ("E2E_WORKSPACE_ROOT", "/Volumes/ZEBRATRENCH"),
        ("COMPOSE_PROJECT_NAME", "original"),
        ("DOCKER_HOST", "tcp://remote:2375"),
        ("PGHOSTADDR", "203.0.113.1"),
        ("E2E_NAMESPACE", "original"),
        ("E2E_WORKER_IMAGE", "mutable:latest"),
    ],
)
def test_target_override_rejected_before_command(environment, monkeypatch, key, value):
    monkeypatch.setattr(fixture, "captured", lambda *_args, **_kwargs: pytest.fail("command ran"))
    with pytest.raises(ValueError):
        fixture.compose(environment | {key: value}, "up", "-d")


def test_diagnostics_never_reveal_expanded_secrets(monkeypatch):
    monkeypatch.setattr(
        subprocess,
        "run",
        lambda *_args, **_kwargs: subprocess.CompletedProcess(
            [], 1, "sentinel-key", "sentinel-key"
        ),
    )
    with pytest.raises(RuntimeError) as caught:
        fixture.captured(["docker", "compose"])
    assert "sentinel-key" not in str(caught.value)


def test_ambient_service_config_not_forwarded(monkeypatch):
    for key in (
        "DOCKER_HOST",
        "COMPOSE_FILE",
        "PGSERVICE",
        "ZEBRA_DATABASE_URL",
        "DEEPSEEK_API_KEY",
    ):
        monkeypatch.setenv(key, "sentinel")
    env = fixture.host_environment()
    assert not any(value == "sentinel" for value in env.values())


def test_compose_is_fixed_project_and_environment_only(environment, monkeypatch):
    calls = []
    monkeypatch.setattr(fixture, "captured", lambda args, **kwargs: calls.append((args, kwargs)))
    fixture.compose(environment, "up", "-d")
    args, kwargs = calls[0]
    assert args[2:4] == ["--project-name", "rabbitmq-product-e2e"]
    assert "sentinel-never-log" not in repr(args)
    assert kwargs["env"]["DEEPSEEK_API_KEY"] == "sentinel-never-log"
    for override in ("--file=original.yml", "--project-name=original", "--env-file=original"):
        with pytest.raises(ValueError):
            fixture.compose(environment, "up", override)


def test_compose_isolation_source_mounts_and_tls():
    config = (fixture.ROOT / "docker/compose.rabbitmq-product-e2e.yml").read_text()
    assert "name: rabbitmq-product-e2e" in config
    assert "external:" not in config and "network_mode:" not in config
    assert "/var/run/docker.sock" not in config and "/Volumes/ZEBRATRENCH:" not in config
    ports = re.findall(r'"([\d.]+:\d+:\d+)"', config)
    assert len(ports) == 6 and all(port.startswith("127.0.0.1:") for port in ports)
    for line in config.splitlines():
        if "E2E_SOURCE_ROOT" in line or "E2E_SECRETS_ROOT" in line:
            assert line.endswith(":ro")
    assert "DOCKER_HOST: " + fixture.RUNTIME_HOST in config
    assert "ZEBRA_RUNTIME_CLASS: gvisor" in config
    assert "ZEBRA_WORKSPACE_VOLUME_ROOT: " + str(fixture.WORKSPACE) in config
    assert "/apps:/app/apps:ro" in config and "/packages:/app/packages:ro" in config
    tls = (HERE / "Caddyfile").read_text()
    assert "host.docker.internal:28000" in tls and "handle_path /broker/*" in tls


@pytest.mark.parametrize(
    "command",
    [
        ["inspect", "fixture"],
        ["image", "inspect", "fixture"],
        ["compose", "up", "-d"],
        ["compose", "down"],
    ],
)
def test_current_context_switch_cannot_redirect_outer_docker(monkeypatch, tmp_path, command):
    # A different config/currentContext is harmless: explicit selection always wins.
    (tmp_path / "config.json").write_text('{"currentContext":"production"}')
    monkeypatch.setenv("DOCKER_CONFIG", str(tmp_path))
    monkeypatch.setenv("DOCKER_CONTEXT", "production")
    monkeypatch.setenv("DOCKER_HOST", "tcp://production:2375")
    calls = []

    def run(args, **kwargs):
        calls.append((args, kwargs))
        assert kwargs["stdin"] == subprocess.DEVNULL
        assert args[:3] == ["docker", "--context", "orbstack"]
        assert "DOCKER_HOST" not in kwargs["env"]
        assert "DOCKER_CONTEXT" not in kwargs["env"]
        output = fixture.OUTER_DOCKER_ENDPOINT if args[3] == "context" else "safe"
        return subprocess.CompletedProcess(args, 0, output, "")

    monkeypatch.setattr(subprocess, "run", run)
    assert fixture.captured(["docker", *command]) == "safe"
    assert len(calls) == 2
    assert calls[0][0][3:6] == ["context", "inspect", "orbstack"]
    assert calls[1][0][3:] == command


def test_non_docker_command_cannot_consume_orchestrator_stdin(monkeypatch):
    def run(args, *, env, stdin, capture_output, text):
        assert args == ["openssl", "version"]
        assert stdin == subprocess.DEVNULL
        assert capture_output and text
        return subprocess.CompletedProcess(args, 0, "safe", "")

    monkeypatch.setattr(subprocess, "run", run)
    assert fixture.captured(["openssl", "version"]) == "safe"


@pytest.mark.parametrize(
    "endpoint",
    [
        "tcp://production:2375",
        "unix:///var/run/docker.sock",
        "",
    ],
)
def test_changed_context_endpoint_blocks_before_mutation(monkeypatch, endpoint):
    calls = []

    def run(args, **_kwargs):
        calls.append(args)
        return subprocess.CompletedProcess(args, 0, endpoint, "")

    monkeypatch.setattr(subprocess, "run", run)
    with pytest.raises(ValueError, match="approved local endpoint"):
        fixture.captured(["docker", "compose", "down"])
    assert len(calls) == 1 and calls[0][3] == "context"


def test_explicit_engine_override_rejected_without_command(monkeypatch):
    monkeypatch.setattr(subprocess, "run", lambda *_a, **_k: pytest.fail("command ran"))
    with pytest.raises(ValueError, match="engine overrides"):
        fixture.captured(["docker", "--context=production", "compose", "down"])


def test_pair_selection_is_pure_and_preserves_secrets(environment):
    original = environment.copy()
    selected = fixture.select_database_pair(environment, "stage3")
    assert fixture.database_pair(selected) == "stage3"
    assert fixture.select_database_pair(selected, "legacy") == original
    assert environment == original
    changed = {key for key in selected if selected[key] != original[key]}
    assert changed == {"ZEBRA_DATABASE_URL", "E2E_ZEBRA_HOST_DSN", "E2E_TRENCH_HOST_DSN"}
    with pytest.raises(ValueError):
        fixture.select_database_pair(environment, "production")


@pytest.mark.parametrize("key", ["ZEBRA_DATABASE_URL", "E2E_ZEBRA_HOST_DSN", "E2E_TRENCH_HOST_DSN"])
@pytest.mark.parametrize("mutation", ["query", "password", "host", "scheme", "pair", "role"])
def test_all_database_endpoints_must_match(environment, key, mutation):
    value = environment[key]
    changed = {
        "query": value + "?hostaddr=203.0.113.1",
        "password": value.replace(environment["E2E_POSTGRES_PASSWORD"], "b" * 48),
        "host": value.replace("@", "@foreign-"),
        "scheme": "other" + value,
        "pair": value.replace("_e2e", "_stage3_e2e"),
        "role": value.replace("e2e:", "foreign:"),
    }[mutation]
    with pytest.raises(ValueError):
        fixture.select_database_pair(environment | {key: changed}, "stage3")


def test_broker_configuration_is_pure_and_consume_requires_diagnostics(environment):
    original = environment.copy()
    assert fixture.configure_broker(environment, {})["ZEBRA_RABBIT_PUBLISH_ENABLED"] == "false"
    rabbit = {
        "RABBITMQ_AMQP_PORT": "25672",
        "ZEBRA_RABBIT_RELAY_PASSWORD": "r" * 32,
        "ZEBRA_RABBIT_CONSUMER_PASSWORD": "c" * 32,
    }
    selected = fixture.configure_broker(environment, rabbit, consume_enabled=True)
    assert selected["ZEBRA_RABBIT_PUBLISH_ENABLED"] == "false"
    assert "zebra-relay:" in selected["ZEBRA_RABBIT_RELAY_URL"]
    assert "zebra-consumer:" in selected["ZEBRA_RABBIT_CONSUMER_URL"]
    assert environment == original
    for replacement in ("foreign", "zebra-consumer", "127.0.0.1", "25673", "%2Ftrench"):
        url = selected["ZEBRA_RABBIT_RELAY_URL"]
        old = {
            "foreign": "host.docker.internal",
            "zebra-consumer": "zebra-relay",
            "127.0.0.1": "host.docker.internal",
            "25673": "25672",
            "%2Ftrench": "%2Fzebra",
        }[replacement]
        with pytest.raises(ValueError):
            fixture.validate_environment(
                selected | {"ZEBRA_RABBIT_RELAY_URL": url.replace(old, replacement)}
            )
    with pytest.raises(ValueError):
        fixture.configure_broker(
            environment, rabbit | {"RABBITMQ_AMQP_PORT": "5672"}, publish_enabled=True
        )
    with pytest.raises(ValueError):
        fixture.configure_broker(environment, {}, fallback_enabled=False)


def test_only_worker_receives_broker_environment():
    config = (fixture.ROOT / "docker/compose.rabbitmq-product-e2e.yml").read_text()
    worker = re.search(r"^  zebra-worker:\n.*?(?=^  \S|\Z)", config, re.M | re.S)
    assert worker is not None
    assert "stop_grace_period: 10m" in worker[0]
    assert "ZEBRA_RABBIT_PUBLISH_ENABLED:-false" in worker[0]
    # The shared cloud anchor must not smuggle worker credentials into the API.
    assert "ZEBRA_RABBIT_" not in config[: worker.start()] + config[worker.end() :]
