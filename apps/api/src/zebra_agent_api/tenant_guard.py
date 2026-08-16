"""Per-request tenant isolation for session-scoped API routes (multi-tenant).

The user/identity system is external (ADR-012): a verified host grant carries
the opaque tenant ``namespace_id``. Sessions created under a grant bind that
namespace durably at TASK_PREPARED projection time. This guard denies any
grant whose namespace does not match the session's bound tenant namespace.
Sessions without a bound namespace (internal/legacy) stay operator-scoped.
"""

from __future__ import annotations

from typing import Any
from uuid import UUID

from agent_core.domain.host_authority import HostContextEnvelope
from agent_core.domain.identifiers import SessionId

from zebra_agent_api.responses import ApiResponse


def tenant_namespace(host_context: HostContextEnvelope | None) -> str | None:
    if host_context is None:
        return None
    namespace = host_context.namespace_id.strip()
    return namespace or None


def tenant_forbidden_response(session_id: str) -> ApiResponse:
    return ApiResponse(
        status_code=404,
        body={
            "status": "not_found",
            "reason": "session does not exist in the caller's namespace",
            "session_id": session_id,
        },
    )


def session_tenant_denied(
    sessions: Any,
    session_id: str,
    host_context: HostContextEnvelope | None,
) -> bool:
    """True when a namespaced session belongs to another tenant."""
    namespace = tenant_namespace(host_context)
    if namespace is None:
        return False
    try:
        parsed = SessionId(UUID(session_id))
    except (ValueError, AttributeError):
        return False
    session = sessions.get_session(parsed)
    if session is None or session.namespace_id is None:
        return False
    return bool(session.namespace_id != namespace)


def session_in_tenant(
    session: object,
    host_context: HostContextEnvelope | None,
) -> bool:
    """List filter: keep unbound sessions and sessions of the caller's tenant."""
    namespace = tenant_namespace(host_context)
    if namespace is None:
        return True
    bound = getattr(session, "namespace_id", None)
    return bound is None or bound == namespace


def scope_session_list_response(
    sessions: Any,
    response: ApiResponse,
    host_context: HostContextEnvelope | None,
) -> ApiResponse:
    """Filter a session/approval listing to the caller's tenant namespace."""
    from uuid import UUID

    from agent_core.domain.identifiers import SessionId

    namespace = tenant_namespace(host_context)
    if namespace is None or response.status_code != 200:
        return response
    body: dict[str, Any] = dict(response.body)
    key = "sessions" if "sessions" in body else "approvals" if "approvals" in body else None
    if key is None:
        return response
    kept: list[dict[str, object]] = []
    for item in body.get(key, []):
        if not isinstance(item, dict):
            continue
        raw_id = item.get("session_id")
        if not isinstance(raw_id, str):
            kept.append(item)
            continue
        try:
            session = sessions.get_session(SessionId(UUID(raw_id)))
        except (ValueError, AttributeError):
            kept.append(item)
            continue
        if session is None or session.namespace_id is None:
            kept.append(item)
            continue
        if session.namespace_id == namespace:
            kept.append(item)
    body[key] = kept
    body["tenant_scope"] = namespace
    return ApiResponse(response.status_code, body)


def tenant_scope_response(
    app: Any,
    request: Any,
) -> ApiResponse | None:
    """Deny cross-tenant access on session-scoped routes; None means allowed.

    Approval ids and task ids resolve to their session (the task surface wraps
    one session), so all three prefixes guard through the same durable tenant
    namespace bound at TASK_PREPARED projection time.
    """
    sessions = app.stores.sessions
    path = request.path
    host_context = getattr(request, "host_context", None)
    for prefix in ("/sessions/", "/approvals/", "/tasks/"):
        if path.startswith(prefix):
            target = path.removeprefix(prefix).split("/")[0]
            if target and session_tenant_denied(sessions, target, host_context):
                return tenant_forbidden_response(target)
    return None
