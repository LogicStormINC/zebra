from __future__ import annotations

from typing import Protocol
from uuid import UUID

from agent_core.domain.identifiers import SessionId
from agent_storage import ControlPlaneStores

from zebra_agent_api.command_submission import submit_session_command
from zebra_agent_api.responses import ApiResponse


class _CommandApp(Protocol):
    stores: ControlPlaneStores


class ApiCommandMixin:
    def queue_cloud_run(
        self: _CommandApp,
        response: ApiResponse,
        *,
        idempotency_key: str | None,
    ) -> ApiResponse:
        if response.status_code != 201:
            return response
        session_text = response.body.get("session_id")
        if not isinstance(session_text, str):
            return response
        try:
            session_id = UUID(session_text)
        except ValueError:
            return response
        events = self.stores.events.list_for_session(SessionId(session_id))
        if not events:
            return response
        command_key = f"{idempotency_key}:run" if idempotency_key else f"run:{session_text}"
        command = submit_session_command(
            self.stores,
            session_text,
            {"kind": "run", "expected_revision": events[-1].sequence},
            idempotency_key=command_key,
        )
        if command.status_code != 202:
            if command.body.get("status") == "duplicate":
                # A concurrent create (or a crash after the run event
                # committed) already queued this exact command — every
                # caller must see the SAME create contract, so the
                # accepted body is rebuilt from the persisted event.
                existing = next(
                    (
                        event
                        for event in self.stores.events.list_for_session(
                            SessionId(session_id)
                        )
                        if event.idempotency_key == command_key
                    ),
                    None,
                )
                if existing is None:
                    return command
                command = _accepted_from_event(existing, session_text)
            else:
                return command
        body = dict(response.body)
        body.update({"executed": False, "status": "queued", "command": command.body})
        return ApiResponse(status_code=201, body=body)

    def submit_command(
        self: _CommandApp,
        session_id: str,
        payload: dict[str, object],
        *,
        idempotency_key: str | None,
    ) -> ApiResponse:
        """Append intent only; a Worker owns the eventual execution side effect."""
        return submit_session_command(
            self.stores,
            session_id,
            payload,
            idempotency_key=idempotency_key,
        )


def _accepted_from_event(event: object, session_text: str) -> ApiResponse:
    """Rebuild the 202-accepted command body from the persisted event."""

    payload = getattr(event, "payload", {})
    return ApiResponse(
        status_code=202,
        body={
            "session_id": session_text,
            "command_id": payload.get("command_id"),
            "kind": payload.get("kind", "run"),
            "status": "accepted",
            "event_type": "session_command_accepted",
            "event_sequence": getattr(event, "sequence", None),
            "expected_revision": payload.get("expected_revision"),
        },
    )
