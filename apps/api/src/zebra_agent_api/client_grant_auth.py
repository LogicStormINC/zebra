"""Client grant authentication for runtime client routes.

V1 (ADR-CLIENT-01): the browser never talks to Zebra directly; the
Host BFF exchanges its own authority for a client session. The runtime
surface therefore authenticates the *client session* (bearer
``client-session id + fence token``) and enforces controller-only
mutations. Direct-browser mode stays disabled.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol
from uuid import UUID

from agent_core.domain.identifiers import ClientSessionId


class ClientGrantAuthorizer(Protocol):
    def authorize(self, headers: dict[str, str] | None) -> ClientAuthContext | None: ...


@dataclass(frozen=True)
class ClientAuthContext:
    client_session_id: ClientSessionId
    fence_token: str

    @property
    def controller(self) -> bool:
        return bool(self.fence_token)


class SessionBackedClientGrantAuthorizer:
    """Validates the session exists and is active; controller rights are
    decided per-action by the control lease fence."""

    def __init__(self, sessions: object) -> None:
        self._sessions = sessions

    def authorize(self, headers: dict[str, str] | None) -> ClientAuthContext | None:
        header = (headers or {}).get("Authorization") or ""
        if not header.startswith("Bearer "):
            return None
        parts = header.removeprefix("Bearer ").strip().split(":", 1)
        if len(parts) != 2:
            return None
        try:
            client_session_id = ClientSessionId(UUID(parts[0]))
        except ValueError:
            return None
        return ClientAuthContext(
            client_session_id=client_session_id, fence_token=parts[1]
        )
