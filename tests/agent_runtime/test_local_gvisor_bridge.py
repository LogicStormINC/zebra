"""Local TLS bridge keeps authentication while avoiding small-packet buffering."""

from pathlib import Path


def test_local_tls_bridge_disables_nagle_and_keeps_client_certificate_verification():
    unit = Path("docker/local-gvisor/zebra-docker-tls.service").read_text()
    command = next(line for line in unit.splitlines() if line.startswith("ExecStart="))
    assert ",nodelay," in command
    assert ",verify=1 " in command and ",cafile=" in command
    assert "OPENSSL-LISTEN:2376" in command and "UNIX-CONNECT:/var/run/docker.sock" in command
