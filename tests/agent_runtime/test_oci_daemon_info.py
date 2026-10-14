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
