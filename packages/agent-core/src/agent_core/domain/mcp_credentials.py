"""Encrypted credential values; no crypto or storage implementation dependencies."""

from dataclasses import dataclass, field
from typing import Literal

from pydantic import BaseModel, ConfigDict, field_validator

from agent_core.domain.extensions import (
    ExtensionRevision,
    ExtensionScope,
    McpConnection,
    OpaqueExtensionId,
)

MAX_TOKEN_BYTES = 16 * 1024


class McpCredentialProtectionError(ValueError):
    """Invalid encrypted material or failed credential verification."""


class McpCredentialBinding(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    deployment_namespace: OpaqueExtensionId
    scope: ExtensionScope
    connection_id: OpaqueExtensionId
    endpoint: str
    auth_mode: Literal["bearer", "api_key", "oauth"]
    credential_ref: OpaqueExtensionId
    credential_revision: ExtensionRevision

    @field_validator("endpoint")
    @classmethod
    def validate_endpoint(cls, value: str) -> str:
        if len(value) > 2048:
            raise ValueError("endpoint exceeds length limit")
        return McpConnection.validate_endpoint(value)


@dataclass(frozen=True)
class SealedMcpCredential:
    key_handle: str
    key_version: str
    nonce: bytes = field(repr=False)
    ciphertext: bytes = field(repr=False)

    def __post_init__(self) -> None:
        if (
            not isinstance(self.key_handle, str)
            or not 1 <= len(self.key_handle) <= 512
            or not isinstance(self.key_version, str)
            or not 1 <= len(self.key_version) <= 512
            or type(self.nonce) is not bytes
            or len(self.nonce) != 12
            or type(self.ciphertext) is not bytes
            or not 17 <= len(self.ciphertext) <= MAX_TOKEN_BYTES + 16
        ):
            raise McpCredentialProtectionError("invalid credential envelope")


@dataclass(frozen=True)
class StoredMcpCredential:
    binding: McpCredentialBinding
    envelope: SealedMcpCredential
