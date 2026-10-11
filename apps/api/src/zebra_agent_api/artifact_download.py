"""Raw private download adapter for task artifacts."""

from __future__ import annotations

import asyncio
import base64
from datetime import UTC, datetime
from time import monotonic
from urllib.parse import quote

from agent_core.domain.host_authority import HostContextEnvelope
from agent_storage.artifact_object_reads import artifact_read_scope, current_artifact_read_scope
from fastapi import Request
from fastapi.responses import JSONResponse, Response

from zebra_agent_api.ag_ui_task_view import authorized_async_read
from zebra_agent_api.responses import ApiResponse
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
    if _artifact_download_request(request) is None:
        return None
    context = getattr(request.state, "host_context", None)
    if context is None:
        return await _download(request, adapter)
    if denied := _authorization_error(context):
        return denied

    async def read() -> Response | None:
        with artifact_read_scope(max_bytes=context.limits.max_artifact_bytes):
            return await _download(request, adapter)

    result = await authorized_async_read(
        read,
        authorization_expires_at=context.expires_at,
        request_deadline=getattr(request.state, "authorization_deadline", None),
    )
    return (
        JSONResponse(status_code=result.status_code, content=result.body)
        if isinstance(result, ApiResponse)
        else result
    )


async def authorized_artifact_read(
    request: Request,
    adapter: RouteAdapter,
    route: RouteRequest,
) -> ApiResponse:
    """HTTP's Artifact GET/HEAD seam; keep authority/audit in the existing adapter.

    The caller selects read routes only. No Grant consumption, mutation or retry
    happens here; cancellation kills actual object I/O before collecting the
    deadline-bounded parent SQL/audit operation.
    """
    if route.method.upper() not in {"GET", "HEAD"}:
        return ApiResponse(405, {"status": "method_not_allowed"})
    context = route.host_context
    if context is None:
        return await asyncio.to_thread(adapter.handle, route)
    if denied := _authorization_error(context):
        return ApiResponse(
            denied.status_code, {"status": "forbidden", "reason": "host_grant_rejected"}
        )
    try:
        context.require_scope("artifact.read")
    except ValueError:
        return ApiResponse(403, {"status": "forbidden", "reason": "artifact_read_not_granted"})

    async def read() -> ApiResponse:
        with artifact_read_scope(max_bytes=context.limits.max_artifact_bytes):
            return await _read_route(adapter, request, route)

    return await authorized_async_read(
        read,
        authorization_expires_at=context.expires_at,
        request_deadline=getattr(request.state, "authorization_deadline", None),
    )


async def _download(request: Request, adapter: RouteAdapter) -> Response | None:
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
    detail = await _read_route(
        adapter,
        request,
        _route_request(
            request,
            f"/tasks/{task_id}/artifacts/{public_id}",
            host_context,
        ),
    )
    if detail.status_code != 200:
        return JSONResponse(status_code=detail.status_code, content=detail.body)
    artifact = detail.body.get("artifact")
    artifact_id = artifact.get("artifact_id") if isinstance(artifact, dict) else None
    if not isinstance(artifact_id, str):
        return _unavailable()
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
        "Content-Disposition": (f"{disposition}; filename*=UTF-8''{quote(file_name)}"),
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
    scope = current_artifact_read_scope()
    if request.method.upper() != "HEAD" and scope is not None and selected_size > scope.max_bytes:
        return _unavailable()
    headers["Content-Length"] = str(selected_size)
    body = b""
    if request.method.upper() != "HEAD":
        query = (
            {"range_start": str(content_range[0]), "range_end": str(content_range[1])}
            if content_range is not None
            else None
        )
        content = await _read_route(
            adapter,
            request,
            _route_request(
                request,
                f"/tasks/{task_id}/artifacts/{artifact_id}/content",
                host_context,
                query=query,
            ),
        )
        if error := _authorization_error(host_context):
            return error
        if content.status_code != 200:
            return JSONResponse(status_code=content.status_code, content=content.body)
        encoded = content.body.get("content_base64")
        if not isinstance(encoded, str) or len(encoded) != 4 * ((selected_size + 2) // 3):
            return _unavailable()
        try:
            body = await asyncio.to_thread(base64.b64decode, encoded, validate=True)
        except ValueError:
            return _unavailable()
        if len(body) != selected_size:
            return _unavailable()
    if error := _authorization_error(host_context):
        return error
    return Response(
        content=body,
        media_type=mime_type,
        headers=headers,
        status_code=status_code,
    )


async def _read_route(
    adapter: RouteAdapter,
    request: Request,
    route: RouteRequest,
) -> ApiResponse:
    if route.host_context is None:
        return await asyncio.to_thread(adapter.handle, route)
    scope = current_artifact_read_scope()
    assert scope is not None
    scope.remaining()
    worker = asyncio.create_task(asyncio.to_thread(adapter.handle, route))
    try:
        result = await asyncio.shield(worker)
        scope.remaining()
        return result
    except BaseException as primary:
        # Cancel actual S3 I/O first, then collect the bounded parent operation.
        # PG audit stays in this worker; an unknown COMMIT is never replayed.
        scope.cancel(primary)
        try:
            async with asyncio.timeout(max(0.01, scope.deadline - monotonic())):
                await asyncio.shield(worker)
        except BaseException as cleanup:
            if not isinstance(cleanup, asyncio.CancelledError):
                primary.add_note(f"Artifact worker cleanup: {type(cleanup).__name__}")
        raise


def _authorization_error(context: HostContextEnvelope | None) -> JSONResponse | None:
    expires_at = getattr(context, "expires_at", None)
    if context is not None and (
        not isinstance(expires_at, datetime)
        or expires_at.utcoffset() is None
        or datetime.now(UTC) >= expires_at
    ):
        return JSONResponse(
            status_code=403,
            content={"status": "forbidden", "reason": "host_grant_rejected"},
        )
    return None


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
        verified_host_grant=getattr(request.state, "verified_host_grant", None),
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
