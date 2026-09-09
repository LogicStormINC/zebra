"""Broker-internal token protection, not credential use authorization."""

from __future__ import annotations

import base64
import json
import os
from dataclasses import dataclass, field
from pathlib import Path

from agent_core.domain.mcp_credentials import (
    MAX_TOKEN_BYTES as MAX_TOKEN_BYTES,
)
from agent_core.domain.mcp_credentials import (
    McpCredentialBinding as McpCredentialBinding,
)
from agent_core.domain.mcp_credentials import (
    McpCredentialProtectionError as McpCredentialProtectionError,
)
from agent_core.domain.mcp_credentials import (
    SealedMcpCredential as SealedMcpCredential,
)
from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from agent_security.secret_store import (
    LocalSecretStore,
    SecretMaterial,
    SecretStore,
    SecretStoreError,
)


def mounted_mcp_protector(
    secret_root: str, key_handle: str, key_version: str,
) -> McpCredentialProtector:
    """Shared API/Worker startup validation for the operator-mounted key."""
    try:
        root = Path(secret_root)
        parts = key_handle.split("/")
        if (
            not root.is_absolute()
            or not key_version
            or any(not part or part in {".", ".."} for part in parts)
        ):
            raise ValueError
        root = root.resolve(strict=True)
        path = root.joinpath(*parts).with_suffix(".json").resolve(strict=True)
        path.relative_to(root)
        if not path.is_file() or path.stat().st_mode & 0o077:
            raise ValueError
        protector = McpCredentialProtector(LocalSecretStore(root), key_handle, key_version)
        protector.validate_active_key()
        return protector
    except (OSError, ValueError):
        raise ValueError("MCP credential master key unavailable or insecure") from None


@dataclass(frozen=True)
class McpCredentialProtector:
    secret_store: SecretStore = field(repr=False)
    active_key_handle: str
    active_key_version: str

    def validate_active_key(self) -> None:
        """Startup readiness check without caching or returning key material."""
        self._key(self.active_key_handle, self.active_key_version)

    def seal(self, binding: McpCredentialBinding, token: str) -> SealedMcpCredential:
        data = _token_bytes(token)
        key = self._key(self.active_key_handle, self.active_key_version)
        nonce = os.urandom(12)
        ciphertext = AESGCM(key).encrypt(
            nonce, data, _associated_data(binding, self.active_key_handle, self.active_key_version)
        )
        return SealedMcpCredential(
            self.active_key_handle, self.active_key_version, nonce, ciphertext
        )

    def unseal(
        self, binding: McpCredentialBinding, envelope: SealedMcpCredential
    ) -> SecretMaterial:
        key = self._key(envelope.key_handle, envelope.key_version)
        try:
            plaintext = (
                AESGCM(key)
                .decrypt(
                    envelope.nonce,
                    envelope.ciphertext,
                    _associated_data(binding, envelope.key_handle, envelope.key_version),
                )
                .decode("ascii")
            )
            _token_bytes(plaintext)
        except (InvalidTag, ValueError):
            raise McpCredentialProtectionError("credential verification failed") from None
        return SecretMaterial(
            handle=binding.credential_ref,
            backend="mcp-aes256gcm-v1",
            version=str(binding.credential_revision),
            value=plaintext,
        )

    def _key(self, handle: str, version: str) -> bytes:
        try:
            material = self.secret_store.get_secret(handle=handle)
            if material.handle != handle or material.version != version or material.value is None:
                raise ValueError
            key = base64.b64decode(material.value, validate=True)
            if len(key) != 32:
                raise ValueError
            return key
        except (SecretStoreError, ValueError):
            raise McpCredentialProtectionError("credential key unavailable") from None


def _token_bytes(token: str) -> bytes:
    if (
        not isinstance(token, str)
        or not 1 <= len(token) <= MAX_TOKEN_BYTES
        or any(not 0x21 <= ord(char) <= 0x7E for char in token)
    ):
        raise McpCredentialProtectionError("invalid credential token")
    return token.encode("ascii")


def _associated_data(binding: McpCredentialBinding, handle: str, version: str) -> bytes:
    return json.dumps(
        {
            "purpose": "zebra-mcp-token-v1",
            "binding": binding.model_dump(mode="json"),
            "key_handle": handle,
            "key_version": version,
        },
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
    ).encode("ascii")
