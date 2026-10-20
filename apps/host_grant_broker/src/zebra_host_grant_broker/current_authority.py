"""Trusted HTTPS authority adapter; credentials are forwarded, never persisted."""

from dataclasses import dataclass
from datetime import UTC, datetime

import httpx

from zebra_host_grant_broker.config import BrokerSettings
from zebra_host_grant_broker.grant_minting import (
    ExchangeRequest,
    GrantMintError,
    _resource_refs,
    _text,
)


class AuthorityError(ValueError):
    """Sanitized authority failure."""


@dataclass(frozen=True, slots=True)
class CurrentAuthority:
    user_id: str
    workspace_id: str
    expires_at: datetime
    scopes: frozenset[str]
    resource_refs: frozenset[tuple[str, str]]

    def authorize(self, request: ExchangeRequest) -> None:
        if not set(request.scopes) <= self.scopes:
            raise GrantMintError("authority_scope_not_allowed")
        if not set(request.resource_refs) <= self.resource_refs:
            raise GrantMintError("authority_resource_not_allowed")


def fetch_authority(
    settings: BrokerSettings,
    body: dict[str, object],
    headers: dict[str, str],
    *,
    expected_principal: str | None = None,
    expected_workspace: str | None = None,
    transport: httpx.BaseTransport | None = None,
) -> CurrentAuthority:
    """The fixed endpoint independently verifies original credentials and current rights.

    Wire response: principalId, workspaceId, hostAppId, namespaceId, scopes,
    resourceRefs, expiresAt (timezone-aware ISO 8601). No entitlement fallback.
    """
    try:
        with httpx.Client(
            timeout=settings.authority_timeout_seconds, transport=transport
        ) as client:
            response = client.post(settings.authority_url, json=body, headers=headers)
    except httpx.HTTPError as exc:
        raise AuthorityError("authority_unreachable") from exc
    if response.status_code != 200:
        raise AuthorityError("authority_rejected")
    try:
        payload = response.json()
        if not isinstance(payload, dict):
            raise ValueError
        principal = _text(payload.get("principalId"), "principal")
        workspace = _text(payload.get("workspaceId"), "workspace")
        if (
            payload.get("hostAppId") != settings.host_app_id
            or payload.get("namespaceId") != settings.namespace_id
            or (expected_principal is not None and principal != expected_principal)
            or (expected_workspace is not None and workspace != expected_workspace)
        ):
            raise AuthorityError("authority_identity_mismatch")
        raw_scopes = payload.get("scopes")
        if not isinstance(raw_scopes, list) or len(raw_scopes) > 64:
            raise ValueError
        scopes = frozenset(_text(scope, "scope") for scope in raw_scopes)
        if len(scopes) != len(raw_scopes):
            raise ValueError
        refs = _resource_refs(payload.get("resourceRefs"))
        expiry = payload.get("expiresAt")
        if not isinstance(expiry, str):
            raise ValueError
        expires_at = datetime.fromisoformat(expiry)
        if expires_at.tzinfo is None or expires_at <= datetime.now(UTC):
            raise AuthorityError("authority_expired")
    except AuthorityError:
        raise
    except (ValueError, TypeError) as exc:
        raise AuthorityError("authority_response_invalid") from exc
    return CurrentAuthority(principal, workspace, expires_at, scopes, frozenset(refs))
