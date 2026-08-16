"""ACP (Agent Client Protocol) entry adapter (ARCH-129-ACP-01).

Maps the ACP entry surface onto the existing durable Session/Event, Policy,
Tool Gateway, approval, clarification, cancellation and resume contracts.
ACP types never enter ``agent-core``; the Session Event Store stays the only
durable authority and every ACP action routes through the same command lane
the HTTP API already uses.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from agent_core.domain.identifiers import SessionId, new_session_id

_ACP_SESSION_PREFIX = "acp"


class AcpAdapterError(ValueError):
    """Raised when an ACP request cannot map onto the durable contracts."""


@dataclass(frozen=True)
class AcpResponse:
    """Protocol-local response envelope; no apps-layer dependency."""

    status_code: int
    body: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class AcpSessionHandle:
    """Stable handle reconnecting clients use; durable id stays internal."""

    acp_session_ref: str
    session_id: SessionId
    last_delivered_sequence: int


class AcpEntryAdapter:
    """Protocol adapter over one API application object.

    All mutating ACP actions delegate to the committed route surface so
    Policy, approval, clarification and effect fencing stay identical to the
    HTTP entry; the adapter owns no second authority.
    """

    def __init__(self, app: Any) -> None:
        self._app = app

    # -- lifecycle ---------------------------------------------------------

    def initialize_session(
        self,
        payload: dict[str, Any],
        *,
        idempotency_key: str | None = None,
    ) -> tuple[AcpSessionHandle, AcpResponse]:
        raw = self._app.create_session(
            payload,
            idempotency_key=idempotency_key,
        )
        response = AcpResponse(status_code=raw.status_code, body=dict(raw.body))
        if response.status_code not in (200, 201):
            raise AcpAdapterError(
                f"ACP session initialize failed: {response.body.get('reason')}"
            )
        session_id = SessionId(response.body["session_id"])
        handle = AcpSessionHandle(
            acp_session_ref=f"{_ACP_SESSION_PREFIX}:{session_id}",
            session_id=session_id,
            last_delivered_sequence=0,
        )
        return handle, response

    def resume_session(
        self,
        acp_session_ref: str,
        *,
        last_delivered_sequence: int,
    ) -> AcpSessionHandle:
        session_id = _parse_acp_ref(acp_session_ref)
        return AcpSessionHandle(
            acp_session_ref=acp_session_ref,
            session_id=session_id,
            last_delivered_sequence=max(last_delivered_sequence, 0),
        )

    # -- streaming ---------------------------------------------------------

    def events_after(
        self,
        handle: AcpSessionHandle,
        *,
        after_sequence: int | None = None,
    ) -> list[Any]:
        """Durable replay from the checkpoint; never repeats completed effects."""
        cursor = (
            after_sequence
            if after_sequence is not None
            else handle.last_delivered_sequence
        )
        return list(
            self._app.stores.events.read_since(handle.session_id, cursor)
        )

    # -- control -----------------------------------------------------------

    def cancel(self, acp_session_ref: str) -> AcpResponse:
        session_id = _parse_acp_ref(acp_session_ref)
        raw = self._app.cancel_session(str(session_id), {})
        return AcpResponse(status_code=raw.status_code, body=dict(raw.body))

    def approve(self, session_id: str, body: dict[str, Any]) -> AcpResponse:
        raw = self._app.approve(session_id, body)
        return AcpResponse(status_code=raw.status_code, body=dict(raw.body))

    def reject(self, session_id: str, body: dict[str, Any]) -> AcpResponse:
        raw = self._app.reject(session_id, body)
        return AcpResponse(status_code=raw.status_code, body=dict(raw.body))

    def new_session_id(self) -> SessionId:
        return new_session_id()


def _parse_acp_ref(acp_session_ref: str) -> SessionId:
    from uuid import UUID

    if not acp_session_ref.startswith(f"{_ACP_SESSION_PREFIX}:"):
        raise AcpAdapterError("ACP session refs must use the acp:<session-id> form")
    raw = acp_session_ref.removeprefix(f"{_ACP_SESSION_PREFIX}:")
    try:
        return SessionId(UUID(raw))
    except (ValueError, TypeError) as error:
        raise AcpAdapterError("ACP session ref does not carry a session id") from error
