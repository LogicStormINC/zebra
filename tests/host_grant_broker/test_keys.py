"""Generic bootstrap must align key IDs and never rotate an existing pair."""

import json

import pytest
from zebra_host_grant_broker.config import BrokerSettings
from zebra_host_grant_broker.keys import generate_keypair, jwk_document, load_private_key


def test_neutral_default_matches_broker_configuration(tmp_path):
    private, public = generate_keypair(tmp_path)
    settings = BrokerSettings.from_env(
        {
            "ZEBRA_GRANT_BROKER_ISSUER": "https://issuer.example",
            "ZEBRA_GRANT_BROKER_ORIGIN": "https://business.example",
            "ZEBRA_GRANT_BROKER_PRIVATE_KEY_FILE": str(private),
            "ZEBRA_GRANT_BROKER_AUTHORITY_URL": "https://business.example/authority",
            "ZEBRA_GRANT_BROKER_HOST_APP_ID": "catalog",
            "ZEBRA_GRANT_BROKER_NAMESPACE_ID": "catalog-prod",
        }
    )
    exported = json.loads(public.read_text())["keys"][0]
    assert private.name == "host-grant-v1.pem"
    assert settings.key_id == exported["kid"] == "host-grant-v1"
    assert exported == jwk_document(load_private_key(settings.private_key_pem), settings.key_id)
    assert private.stat().st_mode & 0o777 == 0o600


@pytest.mark.parametrize("existing", ["private", "public", "both"])
def test_existing_files_are_never_overwritten(tmp_path, existing):
    private, public = generate_keypair(tmp_path, "trench-host-grant-v1")
    before = {p: p.read_bytes() for p in (private, public)}
    if existing == "private":
        public.unlink()
    elif existing == "public":
        private.unlink()
    present = {p: content for p, content in before.items() if p.exists()}
    with pytest.raises(FileExistsError):
        generate_keypair(tmp_path, "trench-host-grant-v1")
    assert {p: p.read_bytes() for p in tmp_path.iterdir()} == present


@pytest.mark.parametrize("key_id", ["../escape", "/absolute", "a/b", "", "x" * 129])
def test_key_id_cannot_escape_output_directory(tmp_path, key_id):
    with pytest.raises(ValueError, match="key ID"):
        generate_keypair(tmp_path, key_id)
    assert list(tmp_path.iterdir()) == []


def test_partial_failure_only_removes_files_created_by_this_call(tmp_path, monkeypatch):
    import zebra_host_grant_broker.keys as keys

    original = keys.os.open
    public = tmp_path / "host-grant-v1.pub.jwks.json"

    def raced_open(path, flags, mode):
        if path == public:
            public.write_text("concurrent-existing-key")
        return original(path, flags, mode)

    monkeypatch.setattr(keys.os, "open", raced_open)
    with pytest.raises(FileExistsError):
        generate_keypair(tmp_path)
    assert not (tmp_path / "host-grant-v1.pem").exists()
    assert public.read_text() == "concurrent-existing-key"
