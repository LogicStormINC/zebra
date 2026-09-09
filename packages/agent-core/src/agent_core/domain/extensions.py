"""Cloud extension configuration values; installation never grants execution authority."""

from __future__ import annotations

from enum import StrEnum
from typing import Annotated, Literal, Self
from urllib.parse import urlsplit

from pydantic import AfterValidator, BaseModel, ConfigDict, Field, field_validator, model_validator

from agent_core.domain.cloud_scope import MAX_AUTHORITY_ISSUER_LENGTH, MAX_NAMESPACE_ID_LENGTH


def _opaque(value: str) -> str:
    if (
        not value
        or value != value.strip()
        or any(ord(char) < 32 or ord(char) == 127 for char in value)
    ):
        raise ValueError("opaque values must be non-blank, trimmed, and free of controls")
    return value


OpaqueExtensionId = Annotated[str, Field(strict=True, max_length=512), AfterValidator(_opaque)]
ExtensionRevision = Annotated[int, Field(strict=True, gt=0)]
ExtensionIdempotencyKey = Annotated[
    str, Field(strict=True, min_length=1, max_length=128, pattern=r"^[\x21-\x7e]+$"),
]
ExtensionDigest = Annotated[str, Field(strict=True, pattern=r"^[0-9a-f]{64}$")]


class ExtensionScope(BaseModel):
    """Exact opaque identity supplied by trusted composition, never inferred from a path."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    authority_issuer: OpaqueExtensionId = Field(max_length=MAX_AUTHORITY_ISSUER_LENGTH)
    namespace_id: OpaqueExtensionId = Field(max_length=MAX_NAMESPACE_ID_LENGTH)
    principal_id: OpaqueExtensionId
    workspace_id: OpaqueExtensionId


class SkillVersion(BaseModel):
    """Pinned artifact metadata; digest verification belongs to artifact materialization."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    skill_id: OpaqueExtensionId
    version_id: OpaqueExtensionId
    artifact_ref: OpaqueExtensionId
    content_digest: ExtensionDigest


class SkillInstallation(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    scope: ExtensionScope
    installation_id: OpaqueExtensionId
    revision: ExtensionRevision
    version: SkillVersion
    enabled: bool = Field(default=True, strict=True)


class McpAuthState(StrEnum):
    NOT_REQUIRED = "not_required"
    PENDING = "pending"
    READY = "ready"
    EXPIRED = "expired"
    REVOKED = "revoked"


class McpAuthMode(StrEnum):
    NONE = "none"
    BEARER = "bearer"
    API_KEY = "api_key"
    OAUTH = "oauth"


class McpConnection(BaseModel):
    """HTTP MCP configuration, not a network or execution authorization.

    Runtime must enforce DNS/IP/redirect egress policy on every request. Private
    development HTTP, if supported, is a deployment policy outside this contract.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    scope: ExtensionScope
    connection_id: OpaqueExtensionId
    revision: ExtensionRevision
    transport: Literal["streamable_http", "sse"] = "streamable_http"
    endpoint: str = Field(max_length=2048)
    credential_ref: OpaqueExtensionId | None = None
    auth_mode: McpAuthMode = McpAuthMode.NONE
    auth_state: McpAuthState = McpAuthState.NOT_REQUIRED
    enabled: bool = Field(default=True, strict=True)

    @field_validator("endpoint")
    @classmethod
    def validate_endpoint(cls, value: str) -> str:
        _opaque(value)
        if any(char.isspace() for char in value) or "\\" in value or "#" in value:
            raise ValueError("endpoint must not contain whitespace, backslashes, or fragments")
        parsed = urlsplit(value)
        if parsed.scheme != "https" or not parsed.hostname or parsed.username is not None:
            raise ValueError("endpoint must be HTTPS with a hostname and no userinfo")
        # Accessing port also rejects malformed and out-of-range ports.
        if parsed.port == 0:
            raise ValueError("endpoint port must be positive")
        return value

    @model_validator(mode="after")
    def validate_auth(self) -> Self:
        if self.auth_mode == McpAuthMode.NONE:
            if self.auth_state != McpAuthState.NOT_REQUIRED or self.credential_ref is not None:
                raise ValueError("none authentication requires not_required and no credential")
        elif self.auth_state == McpAuthState.NOT_REQUIRED:
            raise ValueError("authenticated modes cannot use not_required")
        if self.auth_state == McpAuthState.READY and self.credential_ref is None:
            raise ValueError("ready authentication requires a credential reference")
        return self
