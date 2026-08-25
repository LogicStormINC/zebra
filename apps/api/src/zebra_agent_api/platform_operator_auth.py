"""Platform operator authorization for management routes.

Operators authenticate with a dedicated static bearer token sourced
from ``ZEBRA_PLATFORM_OPERATOR_TOKEN``. In non-local deployments an
unconfigured token fails closed: management routes return 503 rather
than silently opening. Regular HostGrants never carry operator rights.
"""

from __future__ import annotations

from typing import Any, Protocol

from zebra_agent_api.responses import ApiResponse


class PlatformOperatorAuthorizer(Protocol):
    def authorize(self, headers: dict[str, str] | None) -> Any | None: ...


class StaticTokenPlatformOperatorAuthorizer:
    def __init__(self, token: str | None, *, strict: bool) -> None:
        self._token = token.strip() if isinstance(token, str) else None
        self._strict = strict

    def authorize(self, headers: dict[str, str] | None) -> str | None:
        if not self._token:
            return None
        header = (headers or {}).get("Authorization") or ""
        if not header.startswith("Bearer "):
            return None
        if header.removeprefix("Bearer ").strip() == self._token:
            return "platform-operator"
        return None


def authorize_platform_operator(
    authorizer: PlatformOperatorAuthorizer | None,
    headers: dict[str, str] | None,
    *,
    deployment: str,
) -> tuple[str | None, ApiResponse | None]:
    """Return (operator identity, error response)."""

    if authorizer is None or authorizer.authorize(headers) is None:
        if deployment != "local":
            return None, ApiResponse(
                status_code=503,
                body={
                    "status": "unavailable",
                    "reason": "platform_operator_authorizer_unconfigured",
                },
            )
        return None, ApiResponse(
            status_code=401,
            body={"status": "unauthorized", "reason": "platform_operator_token_required"},
        )
    identity = authorizer.authorize(headers)
    return identity, None
