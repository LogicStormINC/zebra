import pytest
from agent_security import (
    REDACTED_SECRET,
    InMemorySecretStore,
    SecretMaterial,
    SecretMissingError,
    SecretStore,
    SecretUnavailableError,
)


def test_secret_material_redacts_runtime_value() -> None:
    secret = SecretMaterial(
        handle=" github/app/private-key ",
        backend=" local-secure-store ",
        version=" v1 ",
        value="super-secret-value",
    )

    assert secret.handle == "github/app/private-key"
    assert secret.backend == "local-secure-store"
    assert secret.version == "v1"
    assert secret.redacted() == {
        "handle": "github/app/private-key",
        "backend": "local-secure-store",
        "version": "v1",
        "value": REDACTED_SECRET,
    }
    assert "super-secret-value" not in repr(secret)
    assert "super-secret-value" not in repr(secret.redacted())


def test_secret_material_rejects_blank_identity_fields() -> None:
    with pytest.raises(ValueError, match="handle"):
        SecretMaterial(handle=" ", backend="memory")
    with pytest.raises(ValueError, match="backend"):
        SecretMaterial(handle="secret/ref", backend=" ")
    with pytest.raises(ValueError, match="version"):
        SecretMaterial(handle="secret/ref", backend="memory", version=" ")
    with pytest.raises(ValueError, match="value"):
        SecretMaterial(handle="secret/ref", backend="memory", value=" ")


def test_in_memory_secret_store_returns_secret_material() -> None:
    secret = SecretMaterial(
        handle="github/app/private-key",
        backend="memory",
        value="super-secret-value",
    )
    store = InMemorySecretStore(secrets={"github/app/private-key": secret})

    resolved = store.get_secret(handle=" github/app/private-key ")

    assert resolved == secret
    assert resolved.redacted()["value"] == REDACTED_SECRET
    assert "super-secret-value" not in repr(store)


def test_in_memory_secret_store_reports_missing_secret() -> None:
    store = InMemorySecretStore()

    with pytest.raises(SecretMissingError, match="missing"):
        store.get_secret(handle="github/app/private-key")


def test_in_memory_secret_store_reports_unavailable() -> None:
    store = InMemorySecretStore(unavailable=True)

    with pytest.raises(SecretUnavailableError, match="unavailable"):
        store.get_secret(handle="github/app/private-key")


def test_in_memory_secret_store_validates_handle() -> None:
    store = InMemorySecretStore()

    with pytest.raises(ValueError, match="handle"):
        store.get_secret(handle=" ")


def test_in_memory_secret_store_satisfies_secret_store_protocol() -> None:
    store = InMemorySecretStore()

    typed_store: SecretStore = store

    assert typed_store is store
