"""User and tenant memory routes extracted from the main adapter cascade."""

from __future__ import annotations

from typing import TYPE_CHECKING

from zebra_agent_api.responses import ApiResponse
from zebra_agent_api.tenant_guard import (
    tenant_forbidden_response,
    tenant_memory_denied,
)

if TYPE_CHECKING:
    from zebra_agent_api.app import ZebraAgentApi
    from zebra_agent_api.routes import RouteRequest


def handle_memory_route(
    app: ZebraAgentApi, request: RouteRequest
) -> ApiResponse | None:
    if not request.path.startswith(("/users/", "/tenants/")):
        return None
    method = request.method.upper()
    parts = (
        _users_path_parts(request.path)
        if request.path.startswith("/users/")
        else _tenants_path_parts(request.path)
    )
    if not parts:
        return None
    if tenant_memory_denied(request.host_context, parts[0]):
        return tenant_forbidden_response(parts[0])
    scope = "user" if request.path.startswith("/users/") else "tenant"
    if method == "GET":
        return _handle_get(app, scope, parts)
    if method == "POST":
        return _handle_post(app, scope, parts, request.body or {})
    return None


def _handle_get(
    app: ZebraAgentApi, scope: str, parts: tuple[str, ...]
) -> ApiResponse | None:
    if len(parts) == 2 and parts[1] == "memory":
        return app.get_user_memory(parts[0]) if scope == "user" else app.get_tenant_memory(parts[0])
    if len(parts) == 3 and parts[1] == "memory" and parts[2] == "queue":
        return (
            app.get_user_memory_queue(parts[0])
            if scope == "user"
            else app.get_tenant_memory_queue(parts[0])
        )
    if len(parts) == 3 and parts[1] == "memory" and parts[2] == "queue-summary":
        return (
            app.get_user_memory_queue_summary(parts[0])
            if scope == "user"
            else app.get_tenant_memory_queue_summary(parts[0])
        )
    return None


def _handle_post(
    app: ZebraAgentApi,
    scope: str,
    parts: tuple[str, ...],
    body: dict[str, object],
) -> ApiResponse | None:
    if len(parts) == 3 and parts[1] == "memory" and parts[2] == "review-queue-preview":
        return (
            app.preview_user_memory_queue(parts[0], body)
            if scope == "user"
            else app.preview_tenant_memory_queue(parts[0], body)
        )
    if len(parts) == 3 and parts[1] == "memory" and parts[2] == "review-queue":
        return (
            app.review_user_memory_queue(parts[0], body)
            if scope == "user"
            else app.review_tenant_memory_queue(parts[0], body)
        )
    if len(parts) == 3 and parts[1] == "memory" and parts[2] == "bulk-review":
        return (
            app.bulk_review_user_memory(parts[0], body)
            if scope == "user"
            else app.bulk_review_tenant_memory(parts[0], body)
        )
    if len(parts) == 4 and parts[1] == "memory" and parts[3] == "confirm":
        return (
            app.confirm_user_memory(parts[0], parts[2], body)
            if scope == "user"
            else app.confirm_tenant_memory(parts[0], parts[2], body)
        )
    if len(parts) == 4 and parts[1] == "memory" and parts[3] == "expire":
        return (
            app.expire_user_memory(parts[0], parts[2], body)
            if scope == "user"
            else app.expire_tenant_memory(parts[0], parts[2], body)
        )
    return None


def _users_path_parts(path: str) -> tuple[str, ...]:
    suffix = path.removeprefix("/users/")
    if not suffix:
        return ()
    return tuple(part for part in suffix.split("/") if part)


def _tenants_path_parts(path: str) -> tuple[str, ...]:
    suffix = path.removeprefix("/tenants/")
    if not suffix:
        return ()
    return tuple(part for part in suffix.split("/") if part)
