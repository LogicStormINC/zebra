"""Pure fake CLI routing tests: no environment credentials or live daemon reads."""

import json
from subprocess import CompletedProcess

import pytest
from agent_core.ports.runtime import RuntimeCapabilityError
from agent_runtime.adapters.oci_engine import PinnedOciEngine


class Runner:
    def __init__(self):
        self.calls = []
        self.daemon = "fake-daemon-a"
        self.endpoint = "tcp://127.0.0.1:1234"

    def __call__(self, command, **kwargs):
        self.calls.append((tuple(command), dict(kwargs)))
        output = ""
        if "context" in command:
            output = json.dumps([{"Endpoints": {"docker": {"Host": self.endpoint}}}])
        if "{{.ID}}" in command:
            output = self.daemon
        if command[-1] == "{{.ID}}\n{{json .Runtimes}}":
            output = self.daemon + '\n{"runc": {}}\n'
        return CompletedProcess(command, 0, output, "")


@pytest.fixture(autouse=True)
def executable(monkeypatch):
    monkeypatch.setattr(
        "agent_runtime.adapters.oci_engine.shutil.which", lambda engine, **kw: engine
    )


@pytest.mark.parametrize(
    "engine,key,flag", [("docker", "DOCKER_HOST", "--host"), ("podman", "CONTAINER_HOST", "--url")]
)
def test_explicit_endpoint_does_not_follow_later_ambient_change(monkeypatch, engine, key, flag):
    runner = Runner()
    env = {key: "tcp://127.0.0.1:1234", "PATH": "/fake"}
    pinned = PinnedOciEngine(engine, env=env, runner=runner)
    identity = pinned.identity
    env[key] = "tcp://victim:4321"
    monkeypatch.setenv(key, "tcp://victim:4321")
    pinned((engine, "rm", "--force", "exact-id"), timeout=5)
    command, kwargs = runner.calls[-1]
    assert command[command.index(flag) + 1] == "tcp://127.0.0.1:1234"
    assert key not in kwargs["env"]
    assert pinned.identity == identity
    if engine == "docker":
        assert not any(arg.startswith("--tls") for arg in command)
        assert "DOCKER_TLS" not in kwargs["env"] and "DOCKER_TLS_VERIFY" not in kwargs["env"]


def test_context_resolved_once_not_reused_for_later_calls():
    runner = Runner()
    pinned = PinnedOciEngine("docker", env={"DOCKER_CONTEXT": "first"}, runner=runner)
    runner.endpoint = "tcp://victim:4321"
    pinned(("docker", "ps"), timeout=1)
    assert sum("context" in command for command, _ in runner.calls) == 1
    assert "DOCKER_CONTEXT" not in runner.calls[-1][1]["env"]
    assert "tcp://127.0.0.1:1234" in runner.calls[-1][0]


def test_daemon_replacement_fails_before_mutation():
    runner = Runner()
    pinned = PinnedOciEngine("docker", env={"DOCKER_HOST": runner.endpoint}, runner=runner)
    runner.daemon = "fake-daemon-b"
    with pytest.raises(RuntimeCapabilityError, match="daemon identity"):
        pinned(("docker", "rm", "exact-id"), timeout=1)
    assert not any("rm" in command for command, _ in runner.calls)


def test_info_checks_identity_in_the_same_read_without_extra_probe():
    runner = Runner()
    pinned = PinnedOciEngine("docker", env={"DOCKER_HOST": runner.endpoint}, runner=runner)
    before = len(runner.calls)
    result = pinned(
        ("docker", "info", "--format", "{{json .Runtimes}}"),
        text=True, capture_output=True, check=False, timeout=10,
    )
    assert len(runner.calls) == before + 1
    assert result.stdout == '{"runc": {}}\n'
    runner.daemon = "replacement"
    with pytest.raises(RuntimeCapabilityError, match="daemon identity"):
        pinned(("docker", "info", "--format", "{{json .Runtimes}}"),
               text=True, capture_output=True, check=False, timeout=10)


@pytest.mark.parametrize("code,output", [(1, "fake-daemon-a\n{}"), (0, ""), (0, "fake-daemon-a")])
def test_failed_or_incomplete_combined_info_is_rejected(code, output):
    runner = Runner()

    def invoke(command, **kwargs):
        if command[-1] == "{{.ID}}\n{{json .Runtimes}}":
            return CompletedProcess(command, code, output, "")
        return runner(command, **kwargs)

    pinned = PinnedOciEngine("docker", env={"DOCKER_HOST": runner.endpoint}, runner=invoke)
    with pytest.raises(RuntimeCapabilityError, match="daemon identity"):
        pinned(("docker", "info", "--format", "{{json .Runtimes}}"),
               text=True, capture_output=True, check=False, timeout=10)


@pytest.mark.parametrize(
    "url",
    [
        "tcp://user:secret@host:1234",
        "ssh://alias",
        "tcp://host",
        "unix://relative",
        "unix:///socket?credential=secret",
        "",
    ],
)
def test_ambiguous_or_credential_endpoint_rejected_without_echo(url):
    with pytest.raises(RuntimeCapabilityError) as error:
        PinnedOciEngine("podman", env={"CONTAINER_HOST": url}, runner=Runner())
    assert "secret" not in str(error.value)


def test_public_tls_certificate_drift_rejected(tmp_path):
    for name in ("ca.pem", "cert.pem", "key.pem"):
        (tmp_path / name).write_text("synthetic")
    pinned = PinnedOciEngine(
        "docker",
        env={
            "DOCKER_HOST": "tcp://127.0.0.1:1234",
            "DOCKER_TLS_VERIFY": "1",
            "DOCKER_CERT_PATH": str(tmp_path),
        },
        runner=Runner(),
    )
    (tmp_path / "ca.pem").write_text("changed")
    with pytest.raises(RuntimeCapabilityError, match="TLS identity"):
        pinned(("docker", "rm", "exact-id"))


def test_conflicting_podman_connection_selector_is_not_silently_discarded():
    runner = Runner()
    with pytest.raises(RuntimeCapabilityError, match="connection selector"):
        PinnedOciEngine(
            "podman",
            env={"CONTAINER_HOST": runner.endpoint, "CONTAINER_CONNECTION": "other-connection"},
            runner=runner,
        )
    assert runner.calls == []
