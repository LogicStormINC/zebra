"""Bounded Host connector URL composition."""

import re
from typing import Any
from urllib.parse import urlsplit, urlunsplit

from agent_core.domain.host_connectors import HostConnectorProfileVersion

from agent_integrations.host_tools.contracts import HostToolGatewayError


def join_endpoint(endpoint: str, suffix: str) -> str:
    if not re.fullmatch(r"/[A-Za-z0-9._~/%-]*", suffix):
        raise HostToolGatewayError("invalid Host connector path", reason="ssrf_blocked")
    parsed = urlsplit(endpoint.strip())
    if parsed.scheme != "https" or not parsed.netloc:
        raise HostToolGatewayError("Host Tool endpoint must be an HTTPS URL", reason="ssrf_blocked")
    if parsed.username is not None or parsed.password is not None:
        raise HostToolGatewayError(
            "Host Tool endpoint must not contain credentials", reason="ssrf_blocked"
        )
    if parsed.query or parsed.fragment:
        raise HostToolGatewayError(
            "Host Tool endpoint must not contain query or fragment", reason="ssrf_blocked"
        )
    base_path = parsed.path.rstrip("/")
    path = f"{base_path}{suffix}"
    return urlunsplit((parsed.scheme, parsed.netloc, path, "", ""))


def profile_gateway_options(profile: HostConnectorProfileVersion) -> dict[str, Any]:
    """Apply frozen paths only for explicit profiles; preserve historical routing."""
    configured = profile.manifest_binding_policy is not None
    return {
        "manifest_binding_policy": profile.manifest_binding_policy or "legacy",
        "reconcile_path": profile.reconcile_path_template,
        "manifest_path": profile.manifest_path if configured else "/manifest",
        "invoke_path": profile.invoke_path_template if configured else None,
    }
