"""Provider-neutral Host authority contracts for Embedded integrations.

This module validates the shape and binding of a Host-signed grant. It does not
verify JWT signatures or persist tokens; those responsibilities belong to a
later adapter at the trust boundary.
"""

from __future__ import annotations

from collections.abc import Iterable
from datetime import UTC, datetime
from typing import Self
from urllib.parse import urlsplit

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

MAX_HOST_APP_ID_LENGTH = 128
MAX_HOST_REFERENCE_LENGTH = 512
MAX_HOST_POLICY_VERSION_LENGTH = 128
MAX_HOST_SCOPE_COUNT = 64
MAX_HOST_RESOURCE_COUNT = 128
MAX_RUNTIME_SECONDS = 86_400
MAX_MODEL_TOKENS = 10_000_000
MAX_ARTIFACT_BYTES = 1_073_741_824


class HostAuthorityError(ValueError):
    """Base error for fail-closed Host authority validation."""


class HostGrantMismatchError(HostAuthorityError):
    """Raised when a grant does not match the composed verifier context."""


class HostGrantNotYetValidError(HostAuthorityError):
    """Raised when a grant is outside its not-before or issued-at window."""


class HostGrantExpiredError(HostAuthorityError):
    """Raised when a grant has expired."""


class HostGrantScopeError(HostAuthorityError):
    """Raised when a grant lacks a required scope or resource binding."""


def _required_text(value: object, field_name: str, max_length: int) -> str:
    if not isinstance(value, str):
        raise ValueError(f"{field_name} must be a string")
    normalized = value.strip()
    if not normalized:
        raise ValueError(f"{field_name} must not be blank")
    if len(normalized) > max_length:
        raise ValueError(f"{field_name} exceeds its maximum length")
    return normalized


def _unique_texts(value: object, field_name: str, max_count: int) -> tuple[str, ...]:
    if isinstance(value, str | bytes) or value is None:
        raise ValueError(f"{field_name} must be a sequence")
    try:
        values: tuple[object, ...] = tuple(value)  # type: ignore[arg-type]
    except TypeError as exc:
        raise ValueError(f"{field_name} must be a sequence") from exc
    if not values or len(values) > max_count:
        raise ValueError(f"{field_name} must contain between 1 and {max_count} values")
    normalized = tuple(
        _required_text(item, field_name, MAX_HOST_REFERENCE_LENGTH) for item in values
    )
    if len(set(normalized)) != len(normalized):
        raise ValueError(f"{field_name} must not contain duplicates")
    return normalized


def _canonical_origin(value: str, field_name: str) -> str:
    normalized = _required_text(value, field_name, 2_048)
    parsed = urlsplit(normalized)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise ValueError(f"{field_name} must be an absolute HTTP(S) origin")
    if parsed.username is not None or parsed.password is not None:
        raise ValueError(f"{field_name} must not contain credentials")
    if parsed.path not in {"", "/"} or parsed.query or parsed.fragment:
        raise ValueError(f"{field_name} must not contain a path, query, or fragment")
    try:
        host = parsed.hostname
        port = parsed.port
    except ValueError as exc:
        raise ValueError(f"{field_name} has an invalid port") from exc
    if host is None:
        raise ValueError(f"{field_name} must contain a host")
    host = host.lower()
    if ":" in host and not host.startswith("["):
        host = f"[{host}]"
    suffix = f":{port}" if port is not None else ""
    return f"{parsed.scheme.lower()}://{host}{suffix}"


class HostResourceRef(BaseModel):
    """Opaque business resource binding granted by the Host."""

    model_config = ConfigDict(frozen=True, extra="forbid", populate_by_name=True)

    resource_type: str = Field(alias="type", max_length=128)
    resource_id: str = Field(alias="id", max_length=MAX_HOST_REFERENCE_LENGTH)

    @field_validator("resource_type", "resource_id")
    @classmethod
    def normalize_reference(cls, value: str, info: object) -> str:
        field_name = getattr(info, "field_name", "resource")
        return _required_text(value, str(field_name), MAX_HOST_REFERENCE_LENGTH)

    @property
    def key(self) -> tuple[str, str]:
        return self.resource_type, self.resource_id


class HostTechnicalLimits(BaseModel):
    """Bounded technical quotas carried by a validated Host grant."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    max_runtime_seconds: int = Field(gt=0, le=MAX_RUNTIME_SECONDS)
    max_model_tokens: int = Field(gt=0, le=MAX_MODEL_TOKENS)
    max_artifact_bytes: int = Field(gt=0, le=MAX_ARTIFACT_BYTES)

    @field_validator("max_runtime_seconds", "max_model_tokens", "max_artifact_bytes", mode="before")
    @classmethod
    def require_integer(cls, value: object) -> object:
        if isinstance(value, bool) or not isinstance(value, int):
            raise ValueError("Host technical limits must be integers")
        return value


class HostContextEnvelope(BaseModel):
    """Validated, non-secret authority context passed to downstream adapters."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    grant_id: str = Field(max_length=MAX_HOST_REFERENCE_LENGTH)
    host_app_id: str = Field(max_length=MAX_HOST_APP_ID_LENGTH)
    namespace_id: str = Field(max_length=MAX_HOST_REFERENCE_LENGTH)
    workspace_ref: str = Field(max_length=MAX_HOST_REFERENCE_LENGTH)
    resource_refs: tuple[HostResourceRef, ...] = Field(
        min_length=1, max_length=MAX_HOST_RESOURCE_COUNT
    )
    scopes: tuple[str, ...] = Field(min_length=1, max_length=MAX_HOST_SCOPE_COUNT)
    limits: HostTechnicalLimits
    origin: str
    policy_version: str = Field(max_length=MAX_HOST_POLICY_VERSION_LENGTH)
    expires_at: datetime | None = None

    @field_validator("grant_id", "host_app_id", "namespace_id", "workspace_ref", "policy_version")
    @classmethod
    def normalize_context_text(cls, value: str, info: object) -> str:
        field_name = getattr(info, "field_name", "context")
        maximum = (
            MAX_HOST_APP_ID_LENGTH
            if field_name == "host_app_id"
            else MAX_HOST_POLICY_VERSION_LENGTH
            if field_name == "policy_version"
            else MAX_HOST_REFERENCE_LENGTH
        )
        return _required_text(value, str(field_name), maximum)

    @field_validator("origin")
    @classmethod
    def normalize_context_origin(cls, value: str) -> str:
        return _canonical_origin(value, "origin")

    @field_validator("expires_at")
    @classmethod
    def normalize_expiry(cls, value: datetime | None) -> datetime | None:
        if value is None:
            return None
        if value.tzinfo is None:
            raise ValueError("expires_at must be timezone-aware")
        return value.astimezone(UTC)

    @field_validator("scopes", mode="before")
    @classmethod
    def normalize_context_scopes(cls, value: object) -> tuple[str, ...]:
        return _unique_texts(value, "scopes", MAX_HOST_SCOPE_COUNT)

    @field_validator("resource_refs")
    @classmethod
    def reject_duplicate_context_resources(
        cls, value: tuple[HostResourceRef, ...]
    ) -> tuple[HostResourceRef, ...]:
        if len({resource.key for resource in value}) != len(value):
            raise ValueError("resource_refs must not contain duplicates")
        return value

    def require_scope(self, scope: str) -> None:
        normalized = _required_text(scope, "scope", MAX_HOST_REFERENCE_LENGTH)
        if normalized not in self.scopes:
            raise HostGrantScopeError(f"scope is not granted: {normalized}")

    def require_resource(self, resource: HostResourceRef) -> None:
        if resource not in self.resource_refs:
            raise HostGrantScopeError(f"resource is not granted: {resource.key}")


class HostSessionGrant(BaseModel):
    """Immutable Host-signed claims after structural validation."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    iss: str = Field(max_length=2_048)
    aud: str = Field(max_length=MAX_HOST_REFERENCE_LENGTH)
    sub: str = Field(max_length=MAX_HOST_REFERENCE_LENGTH)
    jti: str = Field(max_length=MAX_HOST_REFERENCE_LENGTH)
    iat: int
    nbf: int
    exp: int
    host_app_id: str = Field(max_length=MAX_HOST_APP_ID_LENGTH)
    namespace_id: str = Field(max_length=MAX_HOST_REFERENCE_LENGTH)
    workspace_ref: str = Field(max_length=MAX_HOST_REFERENCE_LENGTH)
    resource_refs: tuple[HostResourceRef, ...] = Field(
        min_length=1, max_length=MAX_HOST_RESOURCE_COUNT
    )
    scopes: tuple[str, ...] = Field(min_length=1, max_length=MAX_HOST_SCOPE_COUNT)
    limits: HostTechnicalLimits
    origin: str
    policy_version: str = Field(max_length=MAX_HOST_POLICY_VERSION_LENGTH)

    @field_validator("iss")
    @classmethod
    def normalize_issuer(cls, value: str) -> str:
        return _canonical_origin(value, "iss")

    @field_validator("origin")
    @classmethod
    def normalize_grant_origin(cls, value: str) -> str:
        return _canonical_origin(value, "origin")

    @field_validator(
        "aud", "sub", "jti", "host_app_id", "namespace_id", "workspace_ref", "policy_version"
    )
    @classmethod
    def normalize_claim_text(cls, value: str, info: object) -> str:
        field_name = str(getattr(info, "field_name", "claim"))
        maximum = (
            MAX_HOST_APP_ID_LENGTH
            if field_name == "host_app_id"
            else MAX_HOST_POLICY_VERSION_LENGTH
            if field_name == "policy_version"
            else MAX_HOST_REFERENCE_LENGTH
        )
        return _required_text(value, field_name, maximum)

    @field_validator("scopes", mode="before")
    @classmethod
    def normalize_grant_scopes(cls, value: object) -> tuple[str, ...]:
        return _unique_texts(value, "scopes", MAX_HOST_SCOPE_COUNT)

    @field_validator("resource_refs")
    @classmethod
    def reject_duplicate_grant_resources(
        cls, value: tuple[HostResourceRef, ...]
    ) -> tuple[HostResourceRef, ...]:
        if len({resource.key for resource in value}) != len(value):
            raise ValueError("resource_refs must not contain duplicates")
        return value

    @field_validator("iat", "nbf", "exp", mode="before")
    @classmethod
    def require_timestamp_integer(cls, value: object) -> object:
        if isinstance(value, bool) or not isinstance(value, int):
            raise ValueError("Host grant timestamps must be integers")
        return value

    @model_validator(mode="after")
    def validate_time_order(self) -> Self:
        if self.iat < 0 or self.nbf < 0 or self.exp < 0 or not (self.iat <= self.nbf < self.exp):
            raise ValueError("Host grant timestamps must satisfy 0 <= iat <= nbf < exp")
        return self

    def validate_against(
        self,
        *,
        now: datetime,
        expected_issuer: str,
        expected_audience: str,
        allowed_origins: Iterable[str],
        expected_host_app_id: str | None = None,
        clock_skew_seconds: int = 0,
    ) -> HostContextEnvelope:
        """Validate the grant against trusted composition inputs."""

        if now.tzinfo is None:
            raise HostAuthorityError("now must be timezone-aware")
        if isinstance(clock_skew_seconds, bool) or clock_skew_seconds < 0:
            raise HostAuthorityError("clock_skew_seconds must be a non-negative integer")
        if self.iss != _canonical_origin(expected_issuer, "expected_issuer"):
            raise HostGrantMismatchError("issuer does not match the trusted verifier")
        if self.aud != _required_text(
            expected_audience, "expected_audience", MAX_HOST_REFERENCE_LENGTH
        ):
            raise HostGrantMismatchError("audience does not match the trusted verifier")
        if expected_host_app_id is not None and self.host_app_id != _required_text(
            expected_host_app_id, "expected_host_app_id", MAX_HOST_APP_ID_LENGTH
        ):
            raise HostGrantMismatchError("Host application does not match the trusted verifier")
        raw_origins = tuple(allowed_origins)
        if any(isinstance(origin, str) and origin.strip() == "*" for origin in raw_origins):
            raise HostGrantMismatchError("origin is not in the exact Host allowlist")
        try:
            origins = {_canonical_origin(origin, "allowed_origin") for origin in raw_origins}
        except ValueError as exc:
            raise HostGrantMismatchError("origin allowlist is malformed") from exc
        if not origins or self.origin not in origins or "*" in origins:
            raise HostGrantMismatchError("origin is not in the exact Host allowlist")
        now_seconds = int(now.astimezone(UTC).timestamp())
        if (
            now_seconds + clock_skew_seconds < self.iat
            or now_seconds + clock_skew_seconds < self.nbf
        ):
            raise HostGrantNotYetValidError("Host grant is not yet valid")
        if now_seconds - clock_skew_seconds >= self.exp:
            raise HostGrantExpiredError("Host grant has expired")
        return HostContextEnvelope(
            grant_id=self.jti,
            host_app_id=self.host_app_id,
            namespace_id=self.namespace_id,
            workspace_ref=self.workspace_ref,
            resource_refs=self.resource_refs,
            scopes=self.scopes,
            limits=self.limits,
            origin=self.origin,
            policy_version=self.policy_version,
            expires_at=datetime.fromtimestamp(self.exp, UTC),
        )
