from __future__ import annotations

from typing import Protocol

from agent_core.domain.host_authority import HostContextEnvelope

from zebra_agent_api.app import ZebraAgentApi
from zebra_agent_api.responses import ApiResponse
from zebra_agent_api.task_api import (
    TaskReadApi,
    append_task_message,
    create_task,
    mutate_task,
    rollover_task,
    route_active_task,
)


class TaskRouteRequest(Protocol):
    @property
    def method(self) -> str: ...

    @property
    def path(self) -> str: ...

    @property
    def body(self) -> dict[str, object] | None: ...

    @property
    def headers(self) -> dict[str, str] | None: ...

    @property
    def query(self) -> dict[str, str] | None: ...

    @property
    def host_context(self) -> HostContextEnvelope | None: ...


def handle_task_route(app: ZebraAgentApi, request: TaskRouteRequest) -> ApiResponse | None:
    method = request.method.upper()
    if method == "GET" and request.path == "/tasks":
        return TaskReadApi(app.stores).list(request.query or {})
    if method == "POST" and request.path == "/tasks":
        return create_task(
            app,
            request.body or {},
            idempotency_key=_idempotency_key(request),
            host_context=request.host_context,
        )
    if request.path.startswith("/internal/tasks/"):
        parts = _parts(request.path, "/internal/tasks/")
        if method == "POST" and len(parts) == 3 and parts[1:] == ("segments", "rollover"):
            return rollover_task(
                app,
                parts[0],
                request.body or {},
                idempotency_key=_idempotency_key(request),
            )
        if method == "GET" and len(parts) == 2 and parts[1] == "segments":
            return TaskReadApi(app.stores).internal_segments(parts[0])
        return None
    if not request.path.startswith("/tasks/"):
        return None
    parts = _parts(request.path, "/tasks/")
    if method == "POST" and len(parts) == 2 and parts[1] == "messages":
        return append_task_message(
            app,
            parts[0],
            request.body or {},
            idempotency_key=_idempotency_key(request),
        )
    if (
        method == "POST"
        and len(parts) == 2
        and parts[1]
        in {
            "cancel",
            "suspend",
            "resume",
        }
    ):
        return mutate_task(app, parts[0], parts[1], request.body or {})
    if method == "GET" and len(parts) == 1:
        return TaskReadApi(app.stores).get(parts[0])
    if method == "GET" and len(parts) == 2 and parts[1] == "stream":
        return TaskReadApi(app.stores).stream(parts[0])
    if method == "GET" and len(parts) == 2 and parts[1] == "diff":
        return route_active_task(app.stores, parts[0], app.get_session_diff)
    if method == "GET" and len(parts) == 2 and parts[1] == "context":
        return route_active_task(app.stores, parts[0], app.get_session_context)
    if method == "GET" and len(parts) == 2 and parts[1] == "artifacts":
        return route_active_task(app.stores, parts[0], app.get_session_artifacts)
    if method == "GET" and len(parts) == 3 and parts[1] == "artifacts":
        return route_active_task(
            app.stores,
            parts[0],
            lambda active: app.get_session_artifact_detail(active, parts[2]),
        )
    if method == "GET" and len(parts) == 4 and parts[1] == "artifacts" and parts[3] == "content":
        return route_active_task(
            app.stores,
            parts[0],
            lambda active: app.get_session_artifact_content(active, parts[2]),
        )
    if method == "GET" and len(parts) == 2 and parts[1] == "delivery-audit":
        return route_active_task(app.stores, parts[0], app.get_session_delivery_audit)
    if method == "POST" and len(parts) == 2 and parts[1] == "commit":
        return route_active_task(
            app.stores,
            parts[0],
            lambda active: app.commit_session(
                active,
                request.body or {},
                idempotency_key=_idempotency_key(request),
            ),
        )
    if method == "POST" and len(parts) == 2 and parts[1] == "pull-request":
        return route_active_task(
            app.stores,
            parts[0],
            lambda active: app.open_session_pull_request(
                active,
                request.body or {},
                idempotency_key=_idempotency_key(request),
            ),
        )
    if method == "POST" and len(parts) == 4 and parts[1] == "artifacts" and parts[3] == "prune":
        return route_active_task(
            app.stores,
            parts[0],
            lambda active: app.prune_session_artifact(active, parts[2]),
        )
    return None


def _parts(path: str, prefix: str) -> tuple[str, ...]:
    return tuple(part for part in path.removeprefix(prefix).split("/") if part)


def _idempotency_key(request: TaskRouteRequest) -> str | None:
    return next(
        (
            value.strip()
            for name, value in (request.headers or {}).items()
            if name.lower() == "idempotency-key" and value.strip()
        ),
        None,
    )
