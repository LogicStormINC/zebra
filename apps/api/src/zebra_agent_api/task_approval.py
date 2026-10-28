"""Cloud-only exact-Run approval HTTP adapter; existing Host guard owns authorization."""

from typing import Any, Literal, cast
from uuid import UUID

from agent_core.domain.identifiers import TaskId
from agent_storage import PostgresControlPlaneStores, PostgresEventStore
from agent_storage.postgres.task_approval import task_approval
from pydantic import BaseModel, ConfigDict, Field, ValidationError

from zebra_agent_api.responses import ApiResponse
from zebra_agent_api.session_binding import renew_host_binding_for_command
from zebra_agent_api.tenant_guard import task_access_response


class ApprovalDecisionBody(BaseModel):
    model_config = ConfigDict(extra="forbid")
    approval_event_id: UUID
    expected_revision: int = Field(ge=0, strict=True)
    tool_call_id: str = Field(min_length=1, max_length=256)
    call_fingerprint: str = Field(pattern=r"^[0-9a-f]{64}$")
    decision: Literal["approve", "reject"]


def handle_task_approval(app: Any, request: Any, task_id: str, run_id: str) -> ApiResponse:
    try:
        tid = TaskId(UUID(task_id))
        if not run_id or len(run_id) > 256:
            raise ValueError()
        body = (
            ApprovalDecisionBody.model_validate(request.body or {})
            if request.method == "POST"
            else None
        )
    except (ValueError, ValidationError):
        return ApiResponse(400, {"reason": "invalid_approval_request"})
    denied = task_access_response(
        app,
        task_id,
        request.host_context,
        verified_host_grant=request.verified_host_grant,
        run_id=run_id,
    )
    if denied:
        return denied
    if (
        not isinstance(app.stores, PostgresControlPlaneStores)
        or request.verified_host_grant is None
    ):
        return ApiResponse(403, {"reason": "approval_authority_required"})
    if body is not None and body.decision == "approve":
        # Human waiting may outlive admission authority. Reuse command renewal;
        # only a fresh verified Host grant can renew the frozen ceilings.
        denied = renew_host_binding_for_command(app, task_id, request.verified_host_grant)
        if denied is not None:
            return denied
    try:
        decision = (
            None
            if body is None
            else {
                **body.model_dump(mode="json"),
                "run_id": run_id,
                "operator": (
                    f"host:{request.host_context.host_app_id}:{request.host_context.namespace_id}"
                ),
            }
        )
        receipt = (request.query or {}).get("approval_event_id") if body is None else None
        if receipt is not None:
            receipt = str(UUID(receipt))
        result = task_approval(
            cast(PostgresEventStore, app.stores.events)._database, tid, run_id, decision, receipt
        )
        return ApiResponse(200, result)
    except ValueError as exc:
        return ApiResponse(409, {"reason": str(exc)[:160]})
    except Exception:
        return ApiResponse(503, {"reason": "approval_temporarily_unavailable"})
