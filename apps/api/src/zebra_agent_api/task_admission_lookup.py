"""Current-authority lookup of an original create receipt; never dispatches work."""

from time import monotonic
from typing import Any
from uuid import UUID

from agent_storage.postgres.task_io import task_io_deadline

from zebra_agent_api.idempotency import scoped_idempotency_key
from zebra_agent_api.responses import ApiResponse
from zebra_agent_api.tenant_guard import host_list_context_response, task_access_response


def read_task_admission(app: Any, request: Any) -> ApiResponse:
    if request.method.upper() != "GET":
        return ApiResponse(405, {"status": "method_not_allowed"})
    context = request.host_context
    if context is None:
        return ApiResponse(401, {"status": "unauthorized"})
    denied = host_list_context_response(context, request.verified_host_grant)
    if denied is not None:
        return denied
    key = next(
        (v for k, v in (request.headers or {}).items() if k.lower() == "idempotency-key"), None
    )
    if (
        request.body is not None
        or request.query
        or not isinstance(key, str)
        or not 0 < len(key) <= 128
        or any(ord(c) < 33 or ord(c) > 126 for c in key)
    ):
        return ApiResponse(400, {"status": "invalid_request"})
    try:
        with task_io_deadline(monotonic() + 2):
            record = app.stores.idempotency.get(
                action="session.create", idempotency_key=scoped_idempotency_key(key, context)
            )
            if record is None:
                return ApiResponse(
                    200,
                    {"contract_version": 1, "status": "not_observed", "noncommit_proved": False},
                )
            if record.status_code not in {200, 201}:
                return ApiResponse(409, {"status": "receipt_requires_reconciliation"})
            task = str(
                UUID(str(record.response_body.get("task_id") or record.response_body["session_id"]))
            )
            denied = task_access_response(
                app, task, context, verified_host_grant=request.verified_host_grant
            )
            if denied is not None:
                return denied
            revision = record.response_body.get(
                "active_segment_sequence", record.response_body.get("current_sequence")
            )
            if type(revision) is not int or revision < 0:
                raise ValueError("invalid original revision")
            return ApiResponse(
                200,
                {
                    "contract_version": 1,
                    "status": "recorded",
                    "task_id": task,
                    "prepared_revision": revision,
                    "request_hash": record.request_hash,
                    "noncommit_proved": False,
                },
            )
    except Exception:
        return ApiResponse(503, {"status": "unavailable"})
