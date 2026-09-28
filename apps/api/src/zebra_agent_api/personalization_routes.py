"""Principal-scoped standing instruction routes."""

from __future__ import annotations

from typing import TYPE_CHECKING

from zebra_agent_api.responses import ApiResponse
from zebra_agent_api.tenant_guard import memory_scope_denied, tenant_forbidden_response

if TYPE_CHECKING:
    from zebra_agent_api.app import ZebraAgentApi
    from zebra_agent_api.routes import RouteRequest


def handle_personalization_route(
    app: ZebraAgentApi, request: RouteRequest
) -> ApiResponse | None:
    parts = _path_parts(request.path)
    if parts is None:
        return None
    user_id = parts[0]
    if memory_scope_denied(request.host_context, scope="user", resource_id=user_id):
        return tenant_forbidden_response(user_id)
    method = request.method.upper()
    if method == "GET":
        return app.get_user_personalization(user_id)
    if method == "PUT":
        return app.update_user_personalization(user_id, request.body or {})
    if method == "DELETE":
        return app.clear_user_personalization(user_id, request.body or {})
    return None


def _path_parts(path: str) -> tuple[str, str] | None:
    if not path.startswith("/users/"):
        return None
    parts = tuple(part for part in path.removeprefix("/users/").split("/") if part)
    if len(parts) != 2 or parts[1] != "personalization":
        return None
    return parts[0], parts[1]
