"""Actual initial Compose preparation with real private files and mocked Docker only."""

import importlib.util
import json
import tempfile
from pathlib import Path

spec = importlib.util.spec_from_file_location(
    "prepare", Path(__file__).resolve().parents[1] / "deploy/prepare_remote.py"
)
m = importlib.util.module_from_spec(spec)
spec.loader.exec_module(m)
old = {
    "Image": "sha256:fixture",
    "Config": {"Env": [], "Entrypoint": [], "Cmd": []},
    "Mounts": [],
}
with tempfile.TemporaryDirectory() as directory:
    m.ROOT = Path(directory)
    m.SECRET = m.ROOT / "secrets"
    m.SECRET.mkdir()
    (m.SECRET / "signing.pem").write_bytes(b"test-only")
    settings = {
        "origin": "https://192.168.110.42:18443",
        "browser_origin": "https://192.168.101.7:18443",
        "issuer": "https://erpnext.zebra.local",
        "host_secret": "test-only",
    }
    (m.SECRET / "host-settings.json").write_text(json.dumps(settings))
    ca = m.ROOT / "root.crt"
    ca.write_bytes(b"test-ca")
    m.Path = lambda value: ca if str(value).endswith("authorities/local/root.crt") else Path(value)

    def command(*args, **kwargs):
        if args[:2] == ("docker", "inspect"):
            return json.dumps([old, old]).encode()
        if args[-1] == "/etc/ssl/certs/ca-certificates.crt":
            return b"test-system-ca"
        return b'{"keys": []}'

    m.command = command
    m.prepare()
    compose = json.loads((m.ROOT / "compose.json").read_text())
    for service in compose["services"].values():
        assert set(service["extra_hosts"].values()) == {"192.168.101.7"}
        assert service["environment"]["ZEBRA_AUTHORITY_ISSUER"] == settings["issuer"]
    override = json.loads((m.ROOT / "erpnext-override.json").read_text())
    assert override["services"]["backend"]["extra_hosts"] == {
        "erpnext-agent.zebra.local": "192.168.101.7"
    }
    assert json.loads((m.SECRET / "host-settings.json").read_text()) == settings
print("PASS actual bootstrap uses new transport IP and preserves issuer, signed origin and secrets")
