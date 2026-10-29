"""Current authorized observation only: never execute, retry, repair or hydrate a command."""

import re
from time import monotonic
from typing import Any
from uuid import UUID

from ag_ui.core import RunAgentInput
from agent_core.domain.client_preparation import ClientPreparationContext
from agent_core.domain.events import EventType
from agent_core.domain.identifiers import SessionId, TaskId
from agent_core.ports.client_command_receipts import ClientCommandReceiptReadPort
from agent_storage.postgres.task_io import task_io_deadline

from zebra_agent_api.ag_ui_public_binding import resolve_public_continuation
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


def read_native_preparation(
    app: Any, task: TaskId, segment: SessionId, key: str, *, follow: bool = True
) -> tuple[Any, Any, str] | None:
    header = app.stores.tasks.read_event_header_by_key(task, segment, key)
    if header is None:
        return None
    page = app.stores.tasks.read_event_page(
        task,
        header.task_sequence - 1,
        limit=1,
        max_bytes=1_048_576,
        through_sequence=header.task_sequence,
    )
    if len(page.events) != 1 or page.events[0].event.event_id != header.event_id:
        raise ValueError("original native event coordinate conflicts")
    event = page.events[0].event
    payload = (
        event.payload.get("payload")
        if event.event_type is EventType.SESSION_COMMAND_ACCEPTED
        else event.payload
    )
    if not isinstance(payload, dict):
        raise ValueError("original native preparation is missing")
    next_key = payload.get("client_preparation_source")
    if isinstance(next_key, str):
        if not follow or next_key == key:
            raise ValueError("original preparation pointer is invalid")
        return read_native_preparation(app, task, segment, next_key, follow=False)
    return header, payload, key


def native_interaction_receipt(
    app: Any,
    request: Any,
    profile: Any,
    task: TaskId,
    run: str,
    segment: SessionId,
    operation: UUID,
    effect: UUID | None,
    auth: Any,
    request_hash: str | None,
) -> ApiResponse | None:
    key = (
        f"client-effect-resume:{effect}" if effect is not None else f"agui-interaction:{operation}"
    )
    observed = read_native_preparation(app, task, segment, key)
    if observed is None:
        # Native cancellation uses its original direct-operation UUID, not a command.
        observed = read_native_preparation(
            app, task, segment, f"direct-control:{operation}:session_cancelled"
        )
    if observed is None:
        return None
    header, payload, source_key = observed
    metadata = payload.get("client_preparation")
    value = payload.get("input")
    if not isinstance(metadata, dict) or not isinstance(value, dict):
        raise ValueError("original operation has no captured standard preparation")
    context = ClientPreparationContext.model_validate({**metadata, "input": value})
    if (
        context.projection_version
        != profile.checkpoint_version(
            coverage=app.stores.tasks.read_run_header(task, run).strict_coverage
        )
        or context.operation_id != operation
        or context.task_id != task
        or context.run_id != run
        or context.client_session_id != auth.client_session_id
        or request_hash is not None
        and request_hash != context.request_hash
    ):
        raise PermissionError("original input belongs to another operation or owner")
    if effect is not None:
        reader = app.client_platform.client_effect_receipts
        receipt = reader.read_receipt(effect)
        if receipt is None or receipt.receipt_id != operation:
            raise ValueError("original effect receipt is not observed")
    resolution = resolve_public_continuation(
        app.stores.tasks,
        namespace=getattr(app.stores, "deployment_namespace", None) or "local",
        task_id=task,
        internal_run_id=run,
        source=header,
        profile=profile,
    )
    if resolution.slice is None:
        return ApiResponse(200, {"status": resolution.kind, "runId": resolution.protocol_run_id})
    accepted = RunAgentInput.model_validate(context.input)
    return ApiResponse(
        200,
        {
            "status": "prepared",
            "sourceKey": source_key,
            "threadId": str(task),
            "runId": resolution.slice.run_id,
            "previousRunId": resolution.slice.previous_run_id,
            "input": accepted.model_copy(update={"run_id": resolution.slice.run_id}).model_dump(
                mode="json", by_alias=True, exclude_none=True
            ),
        },
    )
