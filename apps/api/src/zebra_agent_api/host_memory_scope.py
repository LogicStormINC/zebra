"""Host memory management cannot widen from a workspace to all of a user's companies."""

from __future__ import annotations

from typing import TYPE_CHECKING
from uuid import UUID

from agent_core.application.memory_scopes import governed_memory_scope
from agent_core.domain.identifiers import MemoryId
from agent_core.domain.memories import MemoryStatus

from zebra_agent_api.memory_creation import create_user_memory
from zebra_agent_api.responses import ApiResponse, bad_request

if TYPE_CHECKING:
    from zebra_agent_api.app import ZebraAgentApi
    from zebra_agent_api.routes import RouteRequest


def host_memory_response(
    app: ZebraAgentApi, request: RouteRequest, kind: str, parts: tuple[str, ...]
) -> ApiResponse | None:
    context = request.host_context
    if context is None:
        return None  # Preserve local/operator compatibility.
    scope = governed_memory_scope(fallback_repo_id=context.workspace_ref, host_context=context)
    denied = ApiResponse(403, {"status": "memory_scope_denied"})
    if scope is None or kind != "user" or scope.user_id != parts[0]:
        return denied
    method = request.method.upper()
    if len(parts) == 2 and parts[1] == "memory":
        if method == "GET":
            query = scope.query(limit=500).model_copy(update={"statuses": tuple(MemoryStatus)})
            records = app.stores.memories.list(query)
            if any(
                any(
                    getattr(record, field) != getattr(scope, field)
                    for field in ("repo_id", "user_id", "tenant_id")
                )
                for record in records
            ):
                return ApiResponse(503, {"status": "memory_scope_integrity"})
            # No event replay for the management list. Source coordinates remain
            # available without exposing unrelated history or unbounded evidence.
            return ApiResponse(
                200,
                {
                    "user_id": scope.user_id,
                    "workspace_ref": scope.repo_id,
                    "memories": [record.model_dump(mode="json") for record in records],
                },
            )
        if method == "POST":
            body = dict(request.body or {})
            task_id = body.get("source_task_id")
            if not isinstance(task_id, str):
                return bad_request("source_task_id is required")
            body["operator"] = scope.user_id
            return create_user_memory(
                stores=app.stores, user_id=scope.user_id, payload=body, scope=scope
            )
        return denied
    # Queue/bulk/profile APIs use user-wide legacy projections. They must not
    # silently bypass the workspace boundary; individual edits retain native CAS.
    if (
        len(parts) not in {3, 4}
        or parts[1] != "memory"
        or (len(parts) == 4 and parts[3] not in {"confirm", "expire"})
    ):
        return denied
    try:
        record = app.stores.memories.get(MemoryId(UUID(parts[2])))
    except (ValueError, TypeError):
        return denied
    if record is None or any(
        getattr(record, field) != getattr(scope, field)
        for field in ("repo_id", "user_id", "tenant_id")
    ):
        return denied
    return None
