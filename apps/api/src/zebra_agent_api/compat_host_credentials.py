"""Legacy-window compat credential issuer shared by API and Worker."""

from __future__ import annotations

from datetime import UTC, datetime

from agent_core.ports.host_credential_resolver import EphemeralHostCredential

COMPAT_TTL_SECONDS = 900


def compat_host_credential(credential_ref: str) -> EphemeralHostCredential:
    """HMAC-path token during the legacy OAuth/mTLS migration window."""

    return EphemeralHostCredential(
        token=f"compat:{credential_ref}",
        audience="zebra-host-egress",
        scopes=(),
        expires_at_epoch=int(datetime.now(UTC).timestamp()) + COMPAT_TTL_SECONDS,
    )
