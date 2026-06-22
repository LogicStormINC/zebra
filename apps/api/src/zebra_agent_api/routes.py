from __future__ import annotations

from dataclasses import dataclass

from zebra_agent_api.app import ApiResponse, ZebraAgentApi


@dataclass(frozen=True)
class RouteRequest:
    method: str
    path: str


@dataclass(frozen=True)
class RouteAdapter:
    app: ZebraAgentApi

    def handle(self, request: RouteRequest) -> ApiResponse:
        method = request.method.upper()
        if method == "GET" and request.path == "/health":
            return self.app.health()
        if method == "GET" and request.path.startswith("/sessions/"):
            session_id = request.path.removeprefix("/sessions/")
            if not session_id:
                return _not_found(request)
            return self.app.get_session(session_id)
        return _not_found(request)


def _not_found(request: RouteRequest) -> ApiResponse:
    return ApiResponse(
        status_code=404,
        body={
            "method": request.method.upper(),
            "path": request.path,
            "status": "not_found",
        },
    )
