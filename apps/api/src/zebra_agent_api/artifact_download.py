"""Raw private download adapter for task artifacts."""

from __future__ import annotations

import asyncio
import base64
from urllib.parse import quote

from agent_core.domain.host_authority import HostContextEnvelope
from fastapi import Request
from fastapi.responses import JSONResponse, Response

from zebra_agent_api.routes import RouteAdapter, RouteRequest

_INLINE_MIME_TYPES = frozenset(
    {
        "application/json",
        "application/vnd.vegalite+json",
        "application/vnd.vegalite.v6+json",
        "audio/mp4",
        "audio/mpeg",
        "audio/ogg",
        "audio/wav",
        "audio/webm",
        "image/avif",
        "image/gif",
        "image/jpeg",
        "image/png",
        "image/webp",
        "text/vtt",
        "video/mp4",
        "video/ogg",
        "video/webm",
    }
)


async def artifact_download_response(
    request: Request,
    adapter: RouteAdapter,
) -> Response | None:
    parsed = _artifact_download_request(request)
    if parsed is None:
        return None
    host_context = getattr(request.state, "host_context", None)
    if host_context is not None:
        try:
            host_context.require_scope("artifact.read")
        except ValueError:
            return JSONResponse(
                status_code=403,
                content={"status": "forbidden", "reason": "artifact_read_not_granted"},
            )
    task_id, public_id, disposition = parsed
    artifact_id, lookup_error = await _resolve_artifact_id(
        adapter,
        request,
        task_id,
        public_id,
        host_context,
    )
    if lookup_error is not None:
        return lookup_error
    if artifact_id is None:
        return JSONResponse(status_code=404, content={"status": "not_found"})
    detail = await asyncio.to_thread(
        adapter.handle,
        _route_request(
            request,
            f"/tasks/{task_id}/artifacts/{artifact_id}",
            host_context,
        ),
    )
    if detail.status_code != 200:
        return JSONResponse(status_code=detail.status_code, content=detail.body)
    artifact = detail.body.get("artifact")
    delivery = artifact.get("delivery") if isinstance(artifact, dict) else None
    file_name = _delivery_text(delivery, "file_name") or f"artifact-{public_id}.bin"
    mime_type = _delivery_text(delivery, "mime_type") or "application/octet-stream"
    size_bytes = delivery.get("size_bytes") if isinstance(delivery, dict) else None
    if not isinstance(size_bytes, int) or isinstance(size_bytes, bool) or size_bytes < 0:
        return _unavailable()
    if disposition == "inline" and mime_type.lower() not in _INLINE_MIME_TYPES:
        return JSONResponse(
            status_code=415,
            content={"status": "artifact_preview_unsupported", "mime_type": mime_type},
        )
    content_range = _requested_range(request, size_bytes) if disposition == "inline" else None
    if isinstance(content_range, JSONResponse):
        return content_range
    status_code = 200
    headers = {
        "Accept-Ranges": "bytes",
        "Cache-Control": "private, no-store",
        "Content-Disposition": (
            f"{disposition}; filename*=UTF-8''{quote(file_name)}"
        ),
        "Content-Security-Policy": "default-src 'none'; sandbox",
        "ETag": f'"{artifact_id}"',
        "X-Content-Type-Options": "nosniff",
    }
    selected_size = size_bytes
    if content_range is not None:
        start, end = content_range
        selected_size = end - start + 1
        status_code = 206
        headers["Content-Range"] = f"bytes {start}-{end}/{size_bytes}"
    headers["Content-Length"] = str(selected_size)
    body = b""
    if request.method.upper() != "HEAD":
        query = (
            {"range_start": str(content_range[0]), "range_end": str(content_range[1])}
            if content_range is not None
            else None
        )
        content = await asyncio.to_thread(
            adapter.handle,
            _route_request(
                request,
                f"/tasks/{task_id}/artifacts/{artifact_id}/content",
                host_context,
                query=query,
            ),
        )
        if content.status_code != 200:
            return JSONResponse(status_code=content.status_code, content=content.body)
        encoded = content.body.get("content_base64")
        if not isinstance(encoded, str):
            return _unavailable()
        try:
            body = base64.b64decode(encoded, validate=True)
        except ValueError:
            return _unavailable()
        if len(body) != selected_size:
            return _unavailable()
    return Response(
        content=body,
        media_type=mime_type,
        headers=headers,
        status_code=status_code,
    )


async def _resolve_artifact_id(
    adapter: RouteAdapter,
    request: Request,
    task_id: str,
    public_id: str,
    host_context: HostContextEnvelope | None,
) -> tuple[str | None, JSONResponse | None]:
    if ":" in public_id:
        return public_id, None
    listing = await asyncio.to_thread(
        adapter.handle,
        _route_request(request, f"/tasks/{task_id}/artifacts", host_context),
    )
    if listing.status_code != 200:
        return None, JSONResponse(status_code=listing.status_code, content=listing.body)
    artifacts = listing.body.get("artifacts")
    if not isinstance(artifacts, list):
        return None, _unavailable()
    match = next(
        (
            item.get("artifact_id")
            for item in artifacts
            if isinstance(item, dict) and item.get("uri") == f"artifact://{public_id}"
        ),
        None,
    )
    return (match if isinstance(match, str) else None), None


def _route_request(
    request: Request,
    path: str,
    host_context: HostContextEnvelope | None,
    *,
    query: dict[str, str] | None = None,
) -> RouteRequest:
    return RouteRequest(
        method="GET",
        path=path,
        headers=dict(request.headers),
        query=query or {},
        body=None,
        host_context=host_context,
    )


def _delivery_text(delivery: object, field: str) -> str | None:
    if not isinstance(delivery, dict):
        return None
    value = delivery.get(field)
    return value if isinstance(value, str) else None


def _artifact_download_request(request: Request) -> tuple[str, str, str] | None:
    parts = tuple(part for part in request.url.path.split("/") if part)
    if (
        request.method.upper() in {"GET", "HEAD"}
        and len(parts) == 5
        and parts[0] == "tasks"
        and parts[2] == "artifacts"
        and parts[4] in {"download", "preview"}
    ):
        if request.method.upper() == "HEAD" and parts[4] != "preview":
            return None
        return parts[1], parts[3], "inline" if parts[4] == "preview" else "attachment"
    return None


def _requested_range(request: Request, size: int) -> tuple[int, int] | JSONResponse | None:
    if request.method.upper() == "HEAD":
        return None
    header = request.headers.get("range")
    if header is None:
        return None
    if not header.startswith("bytes=") or "," in header or size == 0:
        return _range_not_satisfiable(size)
    value = header.removeprefix("bytes=")
    if "-" not in value:
        return _range_not_satisfiable(size)
    start_text, end_text = value.split("-", maxsplit=1)
    try:
        if not start_text:
            suffix = int(end_text)
            if suffix <= 0:
                return _range_not_satisfiable(size)
            return max(0, size - suffix), size - 1
        start = int(start_text)
        end = int(end_text) if end_text else size - 1
    except ValueError:
        return _range_not_satisfiable(size)
    if start < 0 or start >= size or end < start:
        return _range_not_satisfiable(size)
    return start, min(end, size - 1)


def _range_not_satisfiable(size: int) -> JSONResponse:
    return JSONResponse(
        status_code=416,
        content={"status": "range_not_satisfiable"},
        headers={"Accept-Ranges": "bytes", "Content-Range": f"bytes */{size}"},
    )


def _unavailable() -> JSONResponse:
    return JSONResponse(
        status_code=503,
        content={"status": "artifact_download_unavailable"},
    )
