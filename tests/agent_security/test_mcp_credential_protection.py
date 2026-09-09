import base64
from dataclasses import replace
from unittest.mock import Mock

import pytest
from agent_security.mcp_credential_protection import (
    MAX_TOKEN_BYTES,
    McpCredentialBinding,
    McpCredentialProtectionError,
    McpCredentialProtector,
)
from agent_security.secret_store import InMemorySecretStore, SecretMaterial, SecretUnavailableError
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

TOKEN = "fixture-token-not-a-real-credential"


@pytest.fixture
def binding():
    return McpCredentialBinding(
        deployment_namespace="dev",
        scope={
            "authority_issuer": "trench",
            "namespace_id": "ns",
            "principal_id": "alice",
            "workspace_id": "workspace",
        },
        connection_id="connection",
        endpoint="https://example.test/mcp",
        auth_mode="bearer",
        credential_ref="credential",
        credential_revision=1,
    )


@pytest.fixture
def protector():
    key = base64.b64encode(AESGCM.generate_key(bit_length=256)).decode()
    store = InMemorySecretStore(
        {
            "mcp/key-1": SecretMaterial(
                handle="mcp/key-1",
                backend="fixture",
                version="1",
                value=key,
            )
        }
    )
    return McpCredentialProtector(store, "mcp/key-1", "1")


def test_roundtrip_random_nonce_and_redaction(binding, protector):
    first = protector.seal(binding, TOKEN)
    second = protector.seal(binding, TOKEN)
    assert first.nonce != second.nonce
    assert first.ciphertext != second.ciphertext
    result = protector.unseal(binding, first)
    assert result.value == TOKEN
    assert result.handle == binding.credential_ref
    assert result.version == "1"
    assert TOKEN.encode() not in first.ciphertext
    assert TOKEN not in repr(first) + repr(protector) + repr(result) + str(result.redacted())


@pytest.mark.parametrize(
    "field,value",
    [
        ("deployment_namespace", "other"),
        ("connection_id", "other"),
        ("endpoint", "https://other.test/mcp"),
        ("endpoint", "https://example.test/other"),
        ("auth_mode", "oauth"),
        ("credential_ref", "other"),
        ("credential_revision", 2),
    ],
)
def test_ciphertext_bound_to_connection_context(binding, protector, field, value):
    envelope = protector.seal(binding, TOKEN)
    changed = McpCredentialBinding.model_validate({**binding.model_dump(), field: value})
    with pytest.raises(McpCredentialProtectionError, match="verification failed"):
        protector.unseal(changed, envelope)


@pytest.mark.parametrize(
    "field", ["authority_issuer", "namespace_id", "principal_id", "workspace_id"]
)
def test_ciphertext_bound_to_full_identity(binding, protector, field):
    envelope = protector.seal(binding, TOKEN)
    changed = McpCredentialBinding.model_validate(
        {
            **binding.model_dump(),
            "scope": {**binding.scope.model_dump(), field: "other"},
        }
    )
    with pytest.raises(McpCredentialProtectionError):
        protector.unseal(changed, envelope)


@pytest.mark.parametrize("field", ["nonce", "ciphertext"])
def test_tampering_rejected(binding, protector, field):
    envelope = protector.seal(binding, TOKEN)
    data = getattr(envelope, field)
    corrupted = replace(envelope, **{field: bytes([data[0] ^ 1]) + data[1:]})
    with pytest.raises(McpCredentialProtectionError):
        protector.unseal(binding, corrupted)


def test_rotated_key_retains_old_envelope_readback(binding, protector):
    envelope = protector.seal(binding, TOKEN)
    store = protector.secret_store
    store.secrets["mcp/key-2"] = SecretMaterial(
        handle="mcp/key-2",
        backend="fixture",
        version="2",
        value=base64.b64encode(AESGCM.generate_key(bit_length=256)).decode(),
    )
    rotated = McpCredentialProtector(store, "mcp/key-2", "2")
    assert rotated.unseal(binding, envelope).value == TOKEN
    new_envelope = rotated.seal(binding, TOKEN)
    assert new_envelope.key_handle == "mcp/key-2"
    assert rotated.unseal(binding, new_envelope).value == TOKEN
    del store.secrets["mcp/key-1"]
    with pytest.raises(McpCredentialProtectionError, match="key unavailable"):
        rotated.unseal(binding, envelope)


@pytest.mark.parametrize("value", ["", "bad base64!", "é", base64.b64encode(b"short").decode()])
def test_invalid_key_fails_closed(binding, protector, value):
    material = Mock(handle="mcp/key-1", version="1", value=value)
    invalid = McpCredentialProtector(Mock(get_secret=Mock(return_value=material)), "mcp/key-1", "1")
    with pytest.raises(McpCredentialProtectionError, match="key unavailable"):
        invalid.seal(binding, TOKEN)


def test_key_version_mismatch_and_backend_error_are_sanitized(binding, protector):
    with pytest.raises(McpCredentialProtectionError, match="key unavailable"):
        replace(protector, active_key_version="2").seal(binding, TOKEN)
    store = Mock(get_secret=Mock(side_effect=SecretUnavailableError(TOKEN)))
    with pytest.raises(McpCredentialProtectionError) as error:
        McpCredentialProtector(store, "mcp/key-1", "1").seal(binding, TOKEN)
    assert TOKEN not in str(error.value)
    assert error.value.__suppress_context__


@pytest.mark.parametrize("token", ["", "space token", "x\r\ny", "é", "x" * (MAX_TOKEN_BYTES + 1)])
def test_invalid_token_rejected_before_key_io(binding, token):
    store = Mock()
    with pytest.raises(McpCredentialProtectionError):
        McpCredentialProtector(store, "key", "1").seal(binding, token)
    store.get_secret.assert_not_called()


def test_maximum_token_supported(binding, protector):
    token = "x" * MAX_TOKEN_BYTES
    assert protector.unseal(binding, protector.seal(binding, token)).value == token


def test_key_alias_substitution_rejected_even_with_same_key(binding, protector):
    envelope = protector.seal(binding, TOKEN)
    old_key = protector.secret_store.secrets["mcp/key-1"]
    protector.secret_store.secrets["mcp/alias"] = replace(old_key, handle="mcp/alias")
    with pytest.raises(McpCredentialProtectionError, match="verification failed"):
        protector.unseal(binding, replace(envelope, key_handle="mcp/alias"))


def test_wrong_key_under_same_version_rejected(binding, protector):
    envelope = protector.seal(binding, TOKEN)
    store = protector.secret_store
    store.secrets["mcp/key-1"] = replace(
        store.secrets["mcp/key-1"],
        value=base64.b64encode(AESGCM.generate_key(bit_length=256)).decode(),
    )
    with pytest.raises(McpCredentialProtectionError, match="verification failed"):
        protector.unseal(binding, envelope)


@pytest.mark.parametrize(
    "field,value", [("nonce", b""), ("ciphertext", b"x" * (MAX_TOKEN_BYTES + 17))]
)
def test_malformed_envelope_rejected(binding, protector, field, value):
    with pytest.raises(McpCredentialProtectionError, match="invalid credential envelope"):
        replace(protector.seal(binding, TOKEN), **{field: value})
