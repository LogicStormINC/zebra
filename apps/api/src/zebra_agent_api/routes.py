from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from zebra_agent_api.app import ZebraAgentApi
from zebra_agent_api.responses import ApiResponse


@dataclass(frozen=True)
class RouteRequest:
    method: str
    path: str
    body: dict[str, Any] | None = None
    headers: dict[str, str] | None = None


@dataclass(frozen=True)
class RouteAdapter:
    app: ZebraAgentApi

    def handle(self, request: RouteRequest) -> ApiResponse:
        method = request.method.upper()
        if method == "GET" and request.path == "/health":
            return self.app.health()
        if method == "POST" and request.path == "/sessions":
            return self.app.create_session(request.body or {})
        if method == "POST" and request.path.startswith("/approvals/"):
            parts = _approval_path_parts(request.path)
            if len(parts) == 2 and parts[1] == "approve":
                return self.app.approve(parts[0], request.body or {})
            if len(parts) == 2 and parts[1] == "reject":
                return self.app.reject(parts[0], request.body or {})
        if method == "GET" and request.path == "/approvals":
            return self.app.list_approvals()
        if method == "GET" and request.path.startswith("/approvals/"):
            parts = _approval_path_parts(request.path)
            if len(parts) == 1:
                return self.app.get_approval(parts[0])
        if method == "POST" and request.path.startswith("/sessions/"):
            parts = _session_path_parts(request.path)
            if len(parts) == 2 and parts[1] == "messages":
                return self.app.append_session_message(parts[0], request.body or {})
            if len(parts) == 2 and parts[1] == "suspend":
                return self.app.suspend_session(parts[0], request.body or {})
            if len(parts) == 2 and parts[1] == "resume":
                return self.app.resume_session(parts[0], request.body or {})
            if len(parts) == 2 and parts[1] == "commit":
                return self.app.commit_session(
                    parts[0],
                    request.body or {},
                    idempotency_key=_idempotency_key(request),
                )
            if len(parts) == 2 and parts[1] == "pull-request":
                return self.app.open_session_pull_request(
                    parts[0],
                    request.body or {},
                    idempotency_key=_idempotency_key(request),
                )
        if method == "GET" and request.path.startswith("/sessions/"):
            parts = _session_path_parts(request.path)
            if parts == ():
                return _not_found(request)
            if len(parts) == 1:
                return self.app.get_session(parts[0])
            if len(parts) == 2 and parts[1] == "stream":
                return self.app.get_session_stream(parts[0])
            if len(parts) == 2 and parts[1] == "diff":
                return self.app.get_session_diff(parts[0])
            if len(parts) == 2 and parts[1] == "artifacts":
                return self.app.get_session_artifacts(parts[0])
            if len(parts) == 3 and parts[1] == "artifacts":
                return self.app.get_session_artifact_detail(parts[0], parts[2])
            if len(parts) == 4 and parts[1] == "artifacts" and parts[3] == "content":
                return self.app.get_session_artifact_content(parts[0], parts[2])
            if len(parts) == 2 and parts[1] == "delivery-audit":
                return self.app.get_session_delivery_audit(parts[0])
            return _not_found(request)
        return _not_found(request)


def _session_path_parts(path: str) -> tuple[str, ...]:
    suffix = path.removeprefix("/sessions/")
    if not suffix:
        return ()
    return tuple(part for part in suffix.split("/") if part)


def _approval_path_parts(path: str) -> tuple[str, ...]:
    suffix = path.removeprefix("/approvals/")
    if not suffix:
        return ()
    return tuple(part for part in suffix.split("/") if part)


def _idempotency_key(request: RouteRequest) -> str | None:
    if request.headers is None:
        return None
    for name, value in request.headers.items():
        if name.lower() == "idempotency-key" and value.strip():
            return value.strip()
    return None


def _not_found(request: RouteRequest) -> ApiResponse:
    return ApiResponse(
        status_code=404,
        body={
            "method": request.method.upper(),
            "path": request.path,
            "status": "not_found",
        },
    )
