"""Client grant authentication for runtime client routes.

V1 (ADR-CLIENT-01): the browser never talks to Zebra directly; the
Host BFF exchanges its own authority for a client session. Cloud HTTP keeps
``Authorization`` for the independently verified HostGrant, so runtime client
routes authenticate the *client session* through the dedicated
``X-Zebra-Client-Session`` header. Direct-browser mode stays disabled.
"""

from __future__ import annotations

from dataclasses import dataclass
from hmac import compare_digest
from typing import Protocol
from uuid import UUID

from agent_core.domain.client_sessions import (
    ClientSessionCredential,
    ClientSessionError,
)
from agent_core.domain.host_authority import HostContextEnvelope
from agent_core.domain.identifiers import ClientSessionId
from agent_core.ports.client_session_registry import ClientSessionRegistryPort


class ClientGrantAuthorizer(Protocol):
    def authorize(
        self,
        headers: dict[str, str] | None,
        *,
        host_context: HostContextEnvelope | None = None,
        require_host_context: bool = False,
    ) -> ClientAuthContext | None: ...


@dataclass(frozen=True)
class ClientAuthContext:
    client_session_id: ClientSessionId


class SessionBackedClientGrantAuthorizer:
    """Validates the session exists and is active; controller rights are
    decided per-action by the control lease fence."""

    def __init__(self, sessions: ClientSessionRegistryPort) -> None:
        self._sessions = sessions

    def authorize(
        self,
        headers: dict[str, str] | None,
        *,
        host_context: HostContextEnvelope | None = None,
        require_host_context: bool = False,
    ) -> ClientAuthContext | None:
        header = next(
            (
                value
                for name, value in (headers or {}).items()
                if name.lower() == "x-zebra-client-session"
            ),
            "",
        )
        parts = header.strip().split(":", 1)
        if len(parts) != 2:
            return None
        try:
            client_session_id = ClientSessionId(UUID(parts[0]))
        except ValueError:
            return None
        try:
            credential = ClientSessionCredential(token=parts[1])
            session = self._sessions.get_session(client_session_id)
            if session is None:
                return None
            session.ensure_active()
            if require_host_context and host_context is None:
                return None
            if host_context is not None:
                session.grant.ensure_matches(
                    host_app_id=host_context.host_app_id,
                    namespace_id=host_context.namespace_id,
                    frontend_app_id=session.grant.frontend_app_id,
                    origin=host_context.origin,
                )
        except (ValueError, ClientSessionError):
            return None
        if not compare_digest(session.credential_hash, credential.credential_hash):
            return None
        return ClientAuthContext(client_session_id=client_session_id)
