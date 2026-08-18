"""Ephemeral Host workload credential issuance (no persistence, no logging)."""

from __future__ import annotations

from typing import Protocol

from pydantic import BaseModel, ConfigDict, Field

MAX_AUDIENCE_LENGTH = 512
MAX_CREDENTIAL_REF_LENGTH = 256


class EphemeralHostCredential(BaseModel):
    """Short-lived Host credential held only in Worker process memory."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    token: str = Field(min_length=1)
    audience: str = Field(min_length=1, max_length=MAX_AUDIENCE_LENGTH)
    scopes: tuple[str, ...] = ()
    expires_at_epoch: int = Field(gt=0)

    @property
    def is_bearer_style(self) -> bool:
        return not self.token.startswith("mtls:")


class HostWorkloadCredentialResolverPort(Protocol):
    """Issue per-invocation Host credentials from a connector reference.

    Implementations may back this with OAuth workload identity, mTLS, a
    cloud secret manager exchange, or short-lived HMAC compatibility.
    Returned credentials are never persisted, written into events, or logged
    (plan section 9, phase C credential rules).
    """

    def issue(
        self,
        *,
        credential_ref: str,
        workload_identity_ref: str,
        audience: str,
        scopes: tuple[str, ...],
        ttl_seconds: int,
    ) -> EphemeralHostCredential: ...


def validate_credential_ref(credential_ref: str) -> str:
    text = credential_ref.strip()
    if not text or len(text) > MAX_CREDENTIAL_REF_LENGTH:
        raise ValueError("credential reference must be bounded and non-blank")
    return text
