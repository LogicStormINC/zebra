from __future__ import annotations

from pathlib import Path
from uuid import UUID

from agent_core.domain.identifiers import SessionId
from zebra_agent_worker import SessionControlError, SessionControlService

from zebra_agent_api.responses import ApiResponse, conflict
from zebra_agent_api.session_payloads import (
    parse_cancel_session_payload,
    parse_suspend_session_payload,
)


def cancel_session_control(
    database_path: Path,
    session_id: str,
    payload: dict[str, object],
) -> ApiResponse:
    parsed = parse_cancel_session_payload(payload)
    if isinstance(parsed, ApiResponse):
        return parsed
    del parsed

    try:
        result = SessionControlService(database_path).cancel_session(SessionId(UUID(session_id)))
    except SessionControlError as error:
        message = str(error)
        if message == "session was not found":
            return ApiResponse(
                status_code=404,
                body={"session_id": session_id, "status": "not_found"},
            )
        return conflict(
            session_id=session_id,
            status="not_cancellable",
            reason=message.replace(" ", "_"),
        )

    return ApiResponse(
        status_code=200,
        body={
            "session_id": session_id,
            "cancelled": True,
            "status": "cancelled",
            "workspace_status": result.workspace.status.value,
        },
    )


def suspend_session_control(
    database_path: Path,
    session_id: str,
    payload: dict[str, object],
) -> ApiResponse:
    parsed = parse_suspend_session_payload(payload)
    if isinstance(parsed, ApiResponse):
        return parsed
    del parsed

    try:
        result = SessionControlService(database_path).suspend_session(SessionId(UUID(session_id)))
    except SessionControlError as error:
        message = str(error)
        if message == "session was not found":
            return ApiResponse(
                status_code=404,
                body={"session_id": session_id, "status": "not_found"},
            )
        return conflict(
            session_id=session_id,
            status="not_suspendable",
            reason=message.replace(" ", "_"),
        )

    return ApiResponse(
        status_code=200,
        body={
            "session_id": session_id,
            "suspended": True,
            "status": "suspended",
            "workspace_status": result.workspace.status.value,
            "snapshot_id": result.workspace.snapshot_id,
        },
    )
