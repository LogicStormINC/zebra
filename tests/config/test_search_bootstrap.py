import hashlib
import os
import subprocess
from pathlib import Path


def test_search_bootstrap_preserves_ca_and_service_secret(tmp_path):
    root = Path(__file__).resolve().parents[2]
    ca = tmp_path / "ca"
    ca.mkdir()
    subprocess.run(
        [
            "openssl",
            "req",
            "-x509",
            "-newkey",
            "rsa:2048",
            "-nodes",
            "-days",
            "30",
            "-subj",
            "/CN=Scratch search CA",
            "-keyout",
            str(ca / "ca.key"),
            "-out",
            str(ca / "ca.crt"),
        ],
        check=True,
        capture_output=True,
    )
    (ca / "ca-bundle.crt").write_bytes((ca / "ca.crt").read_bytes())
    digest = hashlib.sha256((ca / "ca.key").read_bytes()).hexdigest()
    secrets = tmp_path / "secrets"
    env = {**os.environ, "ZEBRA_SEARCH_CA_DIR": str(ca), "ZEBRA_SEARCH_SECRETS_DIR": str(secrets)}
    command = ["bash", str(root / "docker/web-search/bootstrap.sh")]
    subprocess.run(command, env=env, check=True, capture_output=True)
    secret = (secrets / "service.env").read_bytes()
    assert len(secret.split(b"=", 1)[1].strip()) == 64
    assert (secrets / "service.env").stat().st_mode & 0o777 == 0o600
    subprocess.run(command, env=env, check=True, capture_output=True)
    assert (secrets / "service.env").read_bytes() == secret
    assert hashlib.sha256((ca / "ca.key").read_bytes()).hexdigest() == digest
    subprocess.run(
        [
            "openssl",
            "verify",
            "-CAfile",
            str(ca / "ca.crt"),
            "-verify_hostname",
            "search.zebra.test",
            str(secrets / "search.crt"),
        ],
        check=True,
        capture_output=True,
    )
