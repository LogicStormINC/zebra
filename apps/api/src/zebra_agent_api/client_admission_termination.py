"""Scoped pre-dispatch termination endpoint; never cancels or retries native effects."""

from typing import Any

from zebra_agent_api.responses import ApiResponse


def terminate_admission(
    app: Any, request: Any, operation: str, scoped: str, digest: str, meta: dict[str, Any]
) -> ApiResponse:
    from agent_storage.postgres.admission_dispatch_fence import FENCE

    from zebra_agent_api.client_admission_operations import _authorize

    store = app.stores.idempotency
    if request.method.upper() == "POST":
        fence = store.admission_fence(scoped, digest, terminate=True)
    else:
        record = store.get(action=FENCE, idempotency_key=scoped)
        if record is not None and record.request_hash != digest:
            return ApiResponse(409, {"status": "admission_operation_conflict"})
        fence = (
            {"state": record.response_body["state"], "recorded_at": record.created_at.isoformat()}
            if record
            else {
                "state": "unresolved"
                if meta.get("dispatch_protocol") == "pre-dispatch/1"
                else "unsupported",
                "recorded_at": "",
            }
        )
    denied = _authorize(app, request, meta)
    return denied or termination_response(operation, digest, meta["kind"], fence)


def termination_response(
    operation: str, digest: str, kind: str, fence: dict[str, str]
) -> ApiResponse:
    return ApiResponse(
        200,
        {
            "contract_version": 1,
            "operation": operation,
            "request_hash": digest,
            "kind": kind,
            "state": fence["state"],
            "recorded_at": fence["recorded_at"],
            "non_commit_proven": fence["state"] == "terminated",
            "retry_allowed": False,
            "controller_reclaim_allowed": False,
        },
    )
