"""Internal per-request credentials; no environment mutation or credential cache."""

from collections.abc import Callable, Mapping
from dataclasses import dataclass, field

from agent_core.domain.mcp_credentials import MAX_TOKEN_BYTES
from agent_security.secret_store import SecretMaterial

from agent_runtime.mcp_protocol import McpProtocolError


@dataclass(frozen=True)
class McpHttpBearerCredential:
    endpoint: str
    secret: SecretMaterial = field(repr=False)


McpHttpCredentialResolver = Callable[[str, Mapping[str, object]], McpHttpBearerCredential]


def resolve_bearer_header(
    resolver: McpHttpCredentialResolver, endpoint: str, frame: Mapping[str, object]
) -> str:
    """Resolver must validate current execution lease, policy and credential authority."""
    try:
        credential = resolver(endpoint, frame)
        if not isinstance(credential, McpHttpBearerCredential) or credential.endpoint != endpoint:
            raise ValueError("credential endpoint mismatch")
        token = credential.secret.value
        if (
            not isinstance(token, str)
            or not 1 <= len(token) <= MAX_TOKEN_BYTES
            or any(not 0x21 <= ord(char) <= 0x7E for char in token)
        ):
            raise ValueError("invalid credential token")
        return f"Bearer {token}"
    except Exception:
        # Authorization failures may include secret backend diagnostics; never forward them.
        raise McpProtocolError("MCP request authorization failed") from None
