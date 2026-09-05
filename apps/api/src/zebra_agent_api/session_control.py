from __future__ import annotations

from pathlib import Path
from typing import Protocol
from uuid import UUID

from agent_core.domain.cloud_scope import OpaqueAuthorityScope
from agent_core.domain.host_authority import HostContextEnvelope
from agent_core.domain.identifiers import SessionId, TaskId
from agent_storage import ControlPlaneStores
from agent_storage.postgres.direct_control import PostgresDirectControl

from zebra_agent_api.responses import ApiResponse, conflict
from zebra_agent_api.session_identity_read import _parse_session_id as parse_session_id
from zebra_agent_api.session_payloads import (
    parse_cancel_session_payload,
    parse_suspend_session_payload,
)


class _ControlApp(Protocol):
    @property
    def database_path(self) -> Path: ...
    @property
    def cloud_control(self) -> PostgresDirectControl | None: ...

    @property
    def stores(self) -> ControlPlaneStores: ...


class ApiSessionControlMixin:
    def cancel_session(
        self: _ControlApp,
        session_id: str,
        payload: dict[str, object],
        *,
        host_context: HostContextEnvelope | None = None,
        trusted_scope: OpaqueAuthorityScope | None = None,
        idempotency_key: str | None = None,
        task_id: TaskId | None = None,
    ) -> ApiResponse:
        session_key = parse_session_id(session_id)
        if isinstance(session_key, ApiResponse):
            return session_key
        return cancel_session_control(
            self.database_path,
            str(session_key),
            payload,
            stores=self.stores,
            cloud_control=self.cloud_control,
            host_context=host_context,
            trusted_scope=trusted_scope,
            idempotency_key=idempotency_key,
            task_id=task_id,
        )

    def suspend_session(
        self: _ControlApp, session_id: str, payload: dict[str, object]
    ) -> ApiResponse:
        session_key = parse_session_id(session_id)
        if isinstance(session_key, ApiResponse):
            return session_key
        return suspend_session_control(
            self.database_path, str(session_key), payload, stores=self.stores
        )


def cancel_session_control(
    database_path: Path,
    session_id: str,
    payload: dict[str, object],
    *,
    stores: ControlPlaneStores | None = None,
    cloud_control: PostgresDirectControl | None = None,
    host_context: HostContextEnvelope | None = None,
    trusted_scope: OpaqueAuthorityScope | None = None,
    idempotency_key: str | None = None,
    task_id: TaskId | None = None,
) -> ApiResponse:
    parsed = parse_cancel_session_payload(payload)
    if isinstance(parsed, ApiResponse):
        return parsed
    del parsed

    try:
        from zebra_agent_api.local_execution import SessionControlError, SessionControlService

        result = SessionControlService(
            database_path, stores=stores, cloud_control=cloud_control
        ).cancel_session(
            SessionId(UUID(session_id)),
            host_context=host_context,
            scope=trusted_scope,
            idempotency_key=idempotency_key,
            task_id=task_id,
        )
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
            "session_id": str(result.event.session_id),
            "cancelled": True,
            "status": "cancelled",
            "workspace_status": result.workspace.status.value,
        },
    )


def suspend_session_control(
    database_path: Path,
    session_id: str,
    payload: dict[str, object],
    *,
    stores: ControlPlaneStores | None = None,
) -> ApiResponse:
    parsed = parse_suspend_session_payload(payload)
    if isinstance(parsed, ApiResponse):
        return parsed
    del parsed

    try:
        from zebra_agent_api.local_execution import SessionControlError, SessionControlService

        result = SessionControlService(database_path, stores=stores).suspend_session(
            SessionId(UUID(session_id))
        )
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
