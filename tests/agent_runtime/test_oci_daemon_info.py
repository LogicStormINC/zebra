"""No daemon or model calls: pooled transport remains fresh and fails closed."""

import json
from subprocess import CompletedProcess
from unittest.mock import Mock

import pytest
from agent_core.ports.runtime import RuntimeCapabilityError
from agent_runtime.adapters import oci_daemon_info as info
from agent_runtime.adapters.oci_engine import PinnedOciEngine


@pytest.fixture
def transport(tmp_path, monkeypatch):
    for name in ("ca.pem", "cert.pem", "key.pem"):
        (tmp_path / name).write_text("synthetic")
    connection = Mock(sock=None)
    response = Mock(status=200)
    response.read.return_value = json.dumps({"ID": "daemon-a"}).encode()
    connection.getresponse.return_value = response
    factory = Mock(return_value=connection)
    monkeypatch.setattr(info, "HTTPSConnection", factory)
    monkeypatch.setattr(info.ssl, "create_default_context", Mock(return_value=Mock()))
    return tmp_path, connection, response, factory


def test_fresh_reads_share_connection_and_reject_changed_private_key(transport):
    root, connection, response, factory = transport
    client = info.DockerDaemonInfo("127.0.0.1", 2376, str(root))
    assert client.identity() == "daemon-a"
    response.read.return_value = b'{"ID":"daemon-b"}'
    assert client.identity() == "daemon-b"
    assert connection.request.call_count == 2 and factory.call_count == 1
    (root / "key.pem").write_text("rotated")
    with pytest.raises(RuntimeCapabilityError, match="TLS identity"):
        client.identity()
    assert connection.request.call_count == 2
    connection.close.assert_called()


@pytest.mark.parametrize("failure", ["timeout", "status", "oversize", "missing", "malformed"])
def test_invalid_read_closes_without_retry(transport, failure):
    root, connection, response, _ = transport
    if failure == "timeout":
        connection.getresponse.side_effect = TimeoutError
    if failure == "status":
        response.status = 503
    if failure == "oversize":
        response.read.return_value = b"x" * 131073
    if failure == "missing":
        response.read.return_value = b"{}"
    if failure == "malformed":
        response.read.return_value = b"not-json"
    client = info.DockerDaemonInfo("127.0.0.1", 2376, str(root))
    with pytest.raises(RuntimeCapabilityError, match="unavailable"):
        client.identity()
    assert connection.request.call_count == 1
    connection.close.assert_called_once()


def test_native_engine_checks_each_fresh_identity_before_mutation(transport, monkeypatch):
    root, connection, response, _ = transport
    monkeypatch.setattr(
        "agent_runtime.adapters.oci_engine.shutil.which", lambda *_a, **_k: "docker"
    )
    pinned = PinnedOciEngine(
        "docker",
        env={
            "DOCKER_HOST": "tcp://127.0.0.1:2376",
            "DOCKER_TLS_VERIFY": "1",
            "DOCKER_CERT_PATH": str(root),
        },
    )
    runner = Mock(return_value=CompletedProcess([], 0, "", ""))
    pinned._runner = runner
    pinned(("docker", "start", "exact"))
    response.read.return_value = b'{"ID":"daemon-b"}'
    with pytest.raises(RuntimeCapabilityError, match="daemon identity"):
        pinned(("docker", "rm", "exact"))
    assert runner.call_count == 1 and connection.request.call_count == 3
    pinned.close()
    connection.close.assert_called()


def test_closed_keepalive_reconnects_only_identity_read(transport):
    from http.client import RemoteDisconnected

    root, connection, response, _ = transport
    connection.getresponse.side_effect = [RemoteDisconnected(), response]
    client = info.DockerDaemonInfo("127.0.0.1", 2376, str(root))
    assert client.identity() == "daemon-a"
    assert connection.request.call_count == 2
    connection.close.assert_called_once()


def test_native_capability_reads_are_fresh_and_share_identity_response(transport, monkeypatch):
    root, connection, response, _ = transport
    monkeypatch.setattr(
        "agent_runtime.adapters.oci_engine.shutil.which", lambda *_a, **_k: "docker"
    )
    pinned = PinnedOciEngine(
        "docker",
        env={
            "DOCKER_HOST": "tcp://127.0.0.1:2376",
            "DOCKER_TLS_VERIFY": "1",
            "DOCKER_CERT_PATH": str(root),
        },
    )
    runner = Mock()
    pinned._runner = runner
    command = ("docker", "info", "--format", "{{.ServerVersion}}\n{{json .Runtimes}}")
    response.read.return_value = b'{"ID":"daemon-a","ServerVersion":"26.1","Runtimes":{"runsc":{}}}'
    first = pinned(command, text=True, capture_output=True, timeout=2)
    assert first.returncode == 0 and first.stdout == '26.1\n{"runsc": {}}'
    response.read.return_value = b'{"ID":"daemon-a","ServerVersion":"26.2","Runtimes":{}}'
    assert pinned(command, text=True, capture_output=True, timeout=2).stdout == "26.2\n{}"
    response.read.return_value = b'{"ID":"daemon-b","ServerVersion":"26.2","Runtimes":{"runsc":{}}}'
    with pytest.raises(RuntimeCapabilityError, match="daemon identity"):
        pinned(command, text=True, capture_output=True, timeout=2)
    assert connection.request.call_count == 4
    runner.assert_not_called()


def test_capability_keeps_original_timeout_type_and_budget(transport, monkeypatch):
    from subprocess import TimeoutExpired

    root, connection, response, _ = transport
    monkeypatch.setattr(
        "agent_runtime.adapters.oci_engine.shutil.which", lambda *_a, **_k: "docker"
    )
    pinned = PinnedOciEngine(
        "docker",
        env={
            "DOCKER_HOST": "tcp://127.0.0.1:2376",
            "DOCKER_TLS_VERIFY": "1",
            "DOCKER_CERT_PATH": str(root),
        },
    )
    pinned._runner = Mock()
    connection.getresponse.side_effect = TimeoutError
    command = ("docker", "info", "--format", "{{.ServerVersion}}\n{{json .Runtimes}}")
    with pytest.raises(TimeoutExpired) as error:
        pinned(command, text=True, capture_output=True, timeout=2)
    assert error.value.timeout == 2 and connection.timeout <= 2
    pinned._runner.assert_not_called()


def test_explicit_connect_tunnel_keeps_target_and_fresh_identity(transport):
    root, connection, response, factory = transport
    client = info.DockerDaemonInfo(
        "192.168.139.232", 2376, str(root), connect_proxy="http://host.docker.internal:7890"
    )
    assert factory.call_args.args == ("host.docker.internal", 7890)
    connection.set_tunnel.assert_called_once_with("192.168.139.232", 2376)
    assert client.identity() == "daemon-a"
    response.read.return_value = b'{"ID":"daemon-b"}'
    assert client.identity() == "daemon-b"
    assert connection.request.call_count == 2
    connection.getresponse.side_effect = OSError("proxy unavailable")
    with pytest.raises(RuntimeCapabilityError):
        client.identity()
    assert factory.call_count == 1  # no direct/CLI fallback


@pytest.mark.parametrize(
    "proxy",
    [
        "https://localhost:7890",
        "http://u:p@localhost:7890",
        "http://localhost:7890/path",
        "http://localhost",
    ],
)
def test_invalid_connect_proxy_fails_closed(transport, proxy):
    root, _, _, factory = transport
    with pytest.raises(RuntimeCapabilityError):
        info.DockerDaemonInfo("192.168.139.232", 2376, str(root), connect_proxy=proxy)
    factory.assert_not_called()


def test_native_cli_reuses_validated_proxy_only_in_private_environment(transport, monkeypatch):
    import os

    root, connection, _, _ = transport
    monkeypatch.setattr(
        "agent_runtime.adapters.oci_engine.shutil.which", lambda *_a, **_k: "docker"
    )
    monkeypatch.setenv("HTTPS_PROXY", "http://ambient:8080")
    environment = {
        "DOCKER_HOST": "tcp://127.0.0.1:2376", "DOCKER_TLS_VERIFY": "1",
        "DOCKER_CERT_PATH": str(root), "ZEBRA_OCI_INFO_CONNECT_PROXY": "http://proxy:7890",
        "NO_PROXY": "*", "no_proxy": "*",
    }
    original = environment.copy()
    pinned = PinnedOciEngine("docker", env=environment)
    runner = Mock(return_value=CompletedProcess([], 0, "", ""))
    pinned._runner = runner
    pinned(("docker", "start", "exact"))
    command = runner.call_args.args[0]
    private = runner.call_args.kwargs["env"]
    assert command[1:4] == ("--host", original["DOCKER_HOST"], "--tlsverify")
    assert command[-2:] == ("start", "exact")
    for key in ("HTTP_PROXY", "HTTPS_PROXY", "http_proxy", "https_proxy"):
        assert private[key] == "http://proxy:7890"
    assert private["NO_PROXY"] == private["no_proxy"] == ""
    assert environment == original and os.environ["HTTPS_PROXY"] == "http://ambient:8080"
    assert connection.request.call_count == 2
    pinned.close()
