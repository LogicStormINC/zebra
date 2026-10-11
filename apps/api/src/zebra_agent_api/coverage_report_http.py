"""Private certified bytes only; HEAD uses the same complete gate as GET."""

import asyncio
from time import monotonic
from uuid import UUID

from agent_core.domain.coverage_contracts import CoverageRefusedError
from agent_core.domain.coverage_validation import CoverageCertificate
from agent_security.host_grant import VerifiedHostGrant
from agent_storage.postgres.coverage_recovery_preparation import remaining_recovery_time
from agent_storage.postgres.database import postgres_deadline
from fastapi import Request
from fastapi.responses import JSONResponse, Response

from zebra_agent_api.responses import ApiResponse
from zebra_agent_api.routes import RouteAdapter, RouteRequest
from zebra_agent_api.tenant_guard import tenant_scope_response


def report_task_id(path: str) -> str | None:
    parts = path.split("/")
    if len(parts) != 5 or parts[1] != "tasks" or parts[3:] != ["coverage", "report"]:
        return None
    try:
        return str(UUID(parts[2]))
    except ValueError:
        return None


async def coverage_report_response(request: Request, adapter: RouteAdapter) -> Response | None:
    task_id = report_task_id(request.url.path)
    if task_id is None or request.method not in {"GET", "HEAD"}:
        return None
    headers = {"Cache-Control": "private, no-store", "X-Content-Type-Options": "nosniff"}

    def refused(status: int, reason: str) -> Response:
        return JSONResponse(status_code=status, content={"status": reason}, headers=headers)

    grant = getattr(request.state, "verified_host_grant", None)
    if type(grant) is not VerifiedHostGrant or grant.context != getattr(
        request.state, "host_context", None
    ):
        return refused(403, "verified_host_grant_required")
    from zebra_agent_api.coverage_report_read import REPORT_READ_SECONDS, read_coverage_report

    deadline = monotonic() + REPORT_READ_SECONDS

    def read() -> tuple[ApiResponse | None, tuple[CoverageCertificate, str, bytes] | None]:
        # One worker/context through owner preflight and proof; no detached timed-out work.
        with postgres_deadline(deadline):
            denied = tenant_scope_response(
                adapter.app,
                RouteRequest(request.method, request.url.path, host_context=grant.context),
            )
            remaining_recovery_time(deadline)
            if denied is not None:
                return denied, None
            result = read_coverage_report(adapter.app, task_id, grant)
            remaining_recovery_time(deadline)
            return None, result

    try:
        denied, result = await asyncio.to_thread(read)
    except PermissionError:
        return refused(403, "coverage_report_authority_invalid")
    except (ValueError, CoverageRefusedError):
        return refused(409, "coverage_report_not_available")
    except Exception:
        # Fixed errors only: provider URLs, credentials and database errors are private.
        return refused(503, "coverage_report_read_unavailable")
    if denied is not None:
        return JSONResponse(status_code=denied.status_code, content=denied.body, headers=headers)
    if result is None:
        return refused(409, "coverage_report_not_certified")
    certificate, _, body = result
    if request.headers.get("range") is not None:
        return refused(416, "coverage_report_range_unsupported")
    headers.update({
        "ETag": f'"{certificate.report_digest}"',
        "X-Coverage-Report-Sha256": certificate.report_digest,
        "Content-Length": str(len(body)),
        "Content-Disposition": f'inline; filename="coverage-{task_id}.json"',
        "Accept-Ranges": "none",
        "Content-Security-Policy": "default-src 'none'; sandbox",
    })
    return Response(
        content=b"" if request.method == "HEAD" else body,
        media_type="application/json", headers=headers,
    )
