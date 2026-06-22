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
            parts = _session_path_parts(request.path)
            if parts == ():
                return _not_found(request)
            if len(parts) == 1:
                return self.app.get_session(parts[0])
            if len(parts) == 2 and parts[1] == "stream":
                return self.app.get_session_stream(parts[0])
            return _not_found(request)
        return _not_found(request)


def _session_path_parts(path: str) -> tuple[str, ...]:
    suffix = path.removeprefix("/sessions/")
    if not suffix:
        return ()
    return tuple(part for part in suffix.split("/") if part)


def _not_found(request: RouteRequest) -> ApiResponse:
    return ApiResponse(
        status_code=404,
        body={
            "method": request.method.upper(),
            "path": request.path,
            "status": "not_found",
        },
    )
