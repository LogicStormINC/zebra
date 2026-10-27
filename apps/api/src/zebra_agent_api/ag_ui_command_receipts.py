"""Current authorized observation only: never execute, retry, repair or hydrate a command."""

import re
from time import monotonic
from typing import Any
from uuid import UUID

from agent_core.domain.identifiers import SessionId, TaskId
from agent_core.ports.client_command_receipts import ClientCommandReceiptReadPort
from agent_storage.postgres.task_io import task_io_deadline

from zebra_agent_api.client_grant_auth import SessionBackedClientGrantAuthorizer
from zebra_agent_api.responses import ApiResponse
from zebra_agent_api.tenant_guard import task_access_response

_ROUTE = re.compile(r"/agui/threads/([^/]+)/runs/([^/]+)/command-receipt")


def handle_client_command_receipt(app: Any, request: Any) -> ApiResponse | None:
    match = _ROUTE.fullmatch(request.path)
    if match is None:
        return None
    if request.method.upper() != "GET":
        return _error(405, "method_not_allowed")
    if request.body is not None or request.query:
        return _error(400, "receipt_input_rejected")
    try:
        task = TaskId(UUID(match[1]))
        run = match[2]
        headers = {k.lower(): v for k, v in (request.headers or {}).items()}
        if headers.get("content-length", "0") != "0" or "transfer-encoding" in headers:
            return _error(400, "receipt_input_rejected")
        key = headers.get("idempotency-key", "")
        segment = SessionId(UUID(headers.get("x-zebra-command-segment", "")))
        if (
            not re.fullmatch(r"[\x21-\x7e]{1,256}", key)
            or len(run) > 128
            or re.search(r"[\x00-\x1f]", run)
        ):
            return _error(400, "receipt_input_rejected")
    except (TypeError, ValueError):
        return _error(400, "receipt_input_rejected")
    platform = getattr(app, "client_platform", None)
    sessions = getattr(platform, "client_sessions", None)
    reader = app.stores.events
    if sessions is None or not isinstance(reader, ClientCommandReceiptReadPort):
        return _error(503, "command_receipt_unavailable")
    authorizer = SessionBackedClientGrantAuthorizer(sessions)
    kwargs = {
        "host_context": request.host_context,
        "require_host_context": app.settings.deployment == "cloud",
        "verified_host_grant": request.verified_host_grant,
    }
    try:
        with task_io_deadline(monotonic() + 2):
            auth = authorizer.authorize(request.headers, **kwargs)
            if auth is None:
                return _error(401, "client_session_authorization_required")
            denied = task_access_response(
                app,
                str(task),
                request.host_context,
                verified_host_grant=request.verified_host_grant,
                run_id=run,
                required_scope="agent.run",
            )
            if denied is not None:
                return denied
            if app.stores.tasks.task_id_for_session(segment) != task:
                return _error(404, "command_receipt_scope_not_found")
            receipt = reader.read_client_command_receipt(
                segment, key, task, run, auth.client_session_id
            )
            current = authorizer.authorize(request.headers, **kwargs)
            if current is None or current.client_session_id != auth.client_session_id:
                return _error(401, "client_session_authorization_required")
            denied = task_access_response(
                app,
                str(task),
                request.host_context,
                verified_host_grant=request.verified_host_grant,
                run_id=run,
                required_scope="agent.run",
            )
            if denied is not None:
                return denied
    except Exception:
        return _error(503, "command_receipt_unavailable")
    return ApiResponse(
        200,
        {"status": "not_observed"}
        if receipt is None
        else {"status": "accepted", "commandId": str(receipt.command_id)},
    )


def _error(code: int, reason: str) -> ApiResponse:
    return ApiResponse(code, {"status": reason})
