"""Fail before Tasks unless the native model wire terminates at this owned fixture."""

import hashlib
import json
import os
import socket
import ssl
from pathlib import Path

import certifi
import httpx
from zebra_agent_config import load_settings


def require_binding(actual: tuple[str, str, str], expected: tuple[str, str, str]) -> None:
    if actual != expected:
        raise RuntimeError("fixture peer, certificate or marker mismatch")


settings = load_settings()
assert settings.model.provider == "deepseek"
assert settings.model.base_url == "https://api.deepseek.com"
assert settings.model.model == "deepseek-v4-pro"
assert settings.model.reviewer_profile == "deepseek-v4-pro-reviewer-v1"
assert os.environ[settings.model.api_key_env] == "synthetic-only"
assert settings.model.max_retries == 0
assert Path(certifi.where()).read_bytes() == Path("/e1/ca.crt").read_bytes()
addresses = {
    row[4][0] for row in socket.getaddrinfo("api.deepseek.com", 443, type=socket.SOCK_STREAM)
}
assert addresses == {"127.0.0.1"}, "fixture resolution changed; refusing provider traffic"
expected = hashlib.sha256(ssl.PEM_cert_to_DER_cert(Path("/e1/model.crt").read_text())).hexdigest()
context = ssl.create_default_context(cafile="/e1/ca.crt")
with socket.create_connection(("127.0.0.1", 443), timeout=3) as connection:
    with context.wrap_socket(connection, server_hostname="api.deepseek.com") as channel:
        peer = channel.getpeername()[0]
        fingerprint = hashlib.sha256(channel.getpeercert(binary_form=True)).hexdigest()
with httpx.Client(trust_env=False, timeout=3) as client:
    response = client.get("https://api.deepseek.com/health")
assert response.status_code == 200
marker = response.headers.get("X-Zebra-E1-Fixture")
binding = (peer, fingerprint, marker)
expected_binding = ("127.0.0.1", expected, "ca-ha-03-e1-20261102")
require_binding(binding, expected_binding)
# Negative checks exercise the SAME guard and local peer; no public traffic.
for index, wrong in enumerate(("203.0.113.1", "0" * 64, "wrong-fixture")):
    rejected = list(expected_binding)
    rejected[index] = wrong
    try:
        require_binding(binding, tuple(rejected))
    except RuntimeError:
        pass
    else:
        raise AssertionError("fixture negative check unexpectedly passed")
print(
    json.dumps(
        {
            "model": "synthetic_native_wire",
            "peer": peer,
            "certificate": fingerprint,
            "marker": marker,
            "negative_peer_certificate_marker": "rejected",
            "real_provider_qualification": False,
        }
    )
)
