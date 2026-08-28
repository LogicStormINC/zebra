"""Raw private download adapter for task artifacts."""

from __future__ import annotations

import asyncio
import base64
from urllib.parse import quote

from agent_core.domain.host_authority import HostContextEnvelope
from fastapi import Request
from fastapi.responses import JSONResponse, Response

from zebra_agent_api.routes import RouteAdapter, RouteRequest


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
    task_id, public_id = parsed
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
    content = await asyncio.to_thread(
        adapter.handle,
        _route_request(
            request,
            f"/tasks/{task_id}/artifacts/{artifact_id}/content",
            host_context,
        ),
    )
    if content.status_code != 200:
        return JSONResponse(status_code=content.status_code, content=content.body)
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
    encoded = content.body.get("content_base64")
    if not isinstance(encoded, str):
        return _unavailable()
    try:
        payload = base64.b64decode(encoded, validate=True)
    except ValueError:
        return _unavailable()
    return Response(
        content=payload,
        media_type=mime_type,
        headers={
            "Cache-Control": "private, no-store",
            "Content-Disposition": f"attachment; filename*=UTF-8''{quote(file_name)}",
            "X-Content-Type-Options": "nosniff",
        },
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
) -> RouteRequest:
    return RouteRequest(
        method="GET",
        path=path,
        headers=dict(request.headers),
        query={},
        body=None,
        host_context=host_context,
    )


def _delivery_text(delivery: object, field: str) -> str | None:
    if not isinstance(delivery, dict):
        return None
    value = delivery.get(field)
    return value if isinstance(value, str) else None


def _artifact_download_request(request: Request) -> tuple[str, str] | None:
    parts = tuple(part for part in request.url.path.split("/") if part)
    if (
        request.method.upper() == "GET"
        and len(parts) == 5
        and parts[0] == "tasks"
        and parts[2] == "artifacts"
        and parts[4] == "download"
    ):
        return parts[1], parts[3]
    return None


def _unavailable() -> JSONResponse:
    return JSONResponse(
        status_code=503,
        content={"status": "artifact_download_unavailable"},
    )
