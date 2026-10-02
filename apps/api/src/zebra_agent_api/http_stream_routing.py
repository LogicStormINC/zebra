"""HTTP stream route predicates (no authorization or execution decisions)."""

from fastapi import Request


def _stream_resource_id(path: str) -> str:
    parts = [part for part in path.split("/") if part]
    if len(parts) >= 3 and parts[:2] == ["agui", "threads"]:
        return parts[2]
    return parts[-2] if len(parts) >= 2 else ""


def _is_stream_request(request: Request) -> bool:
    return request.method.upper() == "GET" and request.url.path.endswith("/stream")


def _is_agui_stream_request(request: Request) -> bool:
    parts = tuple(part for part in request.url.path.split("/") if part)
    return (
        request.method.upper() == "GET"
        and len(parts) == 6
        and parts[:2] == ("agui", "threads")
        and parts[3] == "runs"
        and parts[5] == "stream"
    )
