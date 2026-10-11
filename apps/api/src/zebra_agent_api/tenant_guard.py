"""Per-request tenant isolation for session-scoped API routes (multi-tenant).

The user/identity system is external (ADR-012): a verified host grant carries
the opaque tenant ``namespace_id``. Sessions created under a grant bind that
namespace durably at TASK_PREPARED projection time. This guard denies any
grant whose namespace does not match the session's bound tenant namespace.
Sessions without a bound namespace (internal/legacy) stay operator-scoped.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from agent_core.domain.host_authority import HostContextEnvelope
from agent_core.domain.identifiers import SessionId, TaskId
from agent_core.domain.task_bindings import require_host_thread, require_task_host_context
from agent_core.ports.task_projection_checkpoints import CheckpointNotReady
from agent_security.host_grant import VerifiedHostGrant

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
    if session is None:
        return False
    if session.namespace_id is None:
        return True
    return bool(session.namespace_id != namespace)


def session_in_tenant(
    session: object,
    host_context: HostContextEnvelope | None,
) -> bool:
    """List filter: Host callers see only sessions bound to their tenant."""
    namespace = tenant_namespace(host_context)
    if namespace is None:
        return True
    bound = getattr(session, "namespace_id", None)
    return bound == namespace


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
        if session is not None and session.namespace_id == namespace:
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
    verified = getattr(request, "verified_host_grant", None)
    cloud_host = host_context is not None and bool(
        getattr(app.stores, "deployment_namespace", None)
    )
    if (
        host_context is not None
        and getattr(app.stores, "deployment_namespace", None)
        and path in {"/sessions", "/approvals", "/tasks"}
        and request.method.upper() == "GET"
    ):
        if path == "/approvals":
            response: ApiResponse = app.list_approvals(
                host_context=host_context,
                verified_host_grant=verified,
            )
        else:
            response = app.list_sessions(
                request.query or {},
                host_context=host_context,
                verified_host_grant=verified,
                include_tasks=path == "/tasks",
            )
        return response
    for prefix in ("/sessions/", "/approvals/", "/tasks/"):
        if path.startswith(prefix):
            target = path.removeprefix(prefix).split("/")[0]
            if cloud_host:
                assert host_context is not None
                denied = host_list_context_response(host_context, verified)
                if denied is not None:
                    return denied
            if prefix == "/tasks/" and target:
                task_response = task_access_response(
                    app,
                    target,
                    host_context,
                    verified_host_grant=verified,
                )
                if task_response is not None:
                    return task_response
            elif target:
                if host_context is not None and getattr(app.stores, "deployment_namespace", None):
                    try:
                        task_id = app.stores.tasks.task_id_for_session(SessionId(UUID(target)))
                    except CheckpointNotReady:
                        return ApiResponse(
                            409, {"status": "projection_not_ready", "retryable": True}
                        )
                    except (ValueError, TypeError):
                        return tenant_forbidden_response(target)
                    except Exception:
                        return ApiResponse(503, {"status": "principal_binding_unavailable"})
                    if task_id is None:
                        return tenant_forbidden_response(target)
                    return task_access_response(
                        app,
                        str(task_id),
                        host_context,
                        verified_host_grant=verified,
                    )
                if session_tenant_denied(sessions, target, host_context):
                    return tenant_forbidden_response(target)
    return None


def task_access_response(
    app: Any,
    task_id: str,
    host_context: HostContextEnvelope | None,
    *,
    verified_host_grant: VerifiedHostGrant | None = None,
    run_id: str | None = None,
) -> ApiResponse | None:
    """Fence Task transports; envelope-only callers have verified preflight upstream."""

    issuer = None
    if host_context is not None and verified_host_grant is not None:
        denied = host_list_context_response(host_context, verified_host_grant)
        if denied is not None:
            return denied
        issuer = verified_host_grant.authority_issuer
        runs = [ref.resource_id for ref in host_context.resource_refs if ref.resource_type == "run"]
        if run_id is None and runs:
            run_id = runs[0]

    try:
        if session_tenant_denied(app.stores.sessions, task_id, host_context):
            return tenant_forbidden_response(task_id)
    except Exception:
        return ApiResponse(503, {"status": "tenant_binding_unavailable"})
    return _task_principal_response(
        app,
        task_id,
        host_context,
        authority_issuer=issuer,
        run_id=run_id,
    )


def _task_principal_response(
    app: Any,
    task_id: str,
    host_context: HostContextEnvelope | None,
    *,
    authority_issuer: str | None = None,
    run_id: str | None = None,
) -> ApiResponse | None:
    namespace = getattr(app.stores, "deployment_namespace", None)
    if namespace is None:
        # ponytail: SQLite has no durable TaskBinding authority table; keep local
        # profiles tenant-only until a local binding store is deliberately added.
        return None
    current = _principal_ref(host_context)
    if current is None:
        if host_context is not None:
            return tenant_forbidden_response(task_id)
        return None
    control = getattr(app, "cloud_control", None)
    if control is None or control.deployment_namespace != namespace:
        return ApiResponse(503, {"status": "principal_binding_unavailable"})
    try:
        binding = control.load_task_binding(TaskId(UUID(task_id)))
    except CheckpointNotReady:
        return ApiResponse(409, {"status": "projection_not_ready", "retryable": True})
    except (ValueError, TypeError):
        return tenant_forbidden_response(task_id)
    except Exception:
        return ApiResponse(503, {"status": "principal_binding_unavailable"})
    if binding is None:
        return tenant_forbidden_response(task_id)
    try:
        assert host_context is not None
        require_task_host_context(
            binding,
            host_context,
            task_id=str(UUID(task_id)),
            now=datetime.now(UTC),
            authority_issuer=authority_issuer,
            run_id=run_id,
        )
    except ValueError:
        return tenant_forbidden_response(task_id)
    return None


def host_list_context_response(
    context: HostContextEnvelope,
    verified: VerifiedHostGrant | None,
) -> ApiResponse | None:
    """An envelope alone cannot supply the issuer needed by exact list fences."""
    if (
        not isinstance(verified, VerifiedHostGrant)
        or verified.context != context
        or context.expires_at is None
        or datetime.now(UTC) >= context.expires_at
        or _principal_ref(context) is None
        or len([ref for ref in context.resource_refs if ref.resource_type == "run"]) > 1
    ):
        return ApiResponse(403, {"status": "host_grant_rejected"})
    try:
        require_host_thread(context)
        context.require_scope("agent.run")
    except ValueError:
        return ApiResponse(403, {"status": "host_grant_rejected"})
    return None


def _principal_ref(context: HostContextEnvelope | None) -> str | None:
    if context is None:
        return None
    refs = [
        resource.resource_id
        for resource in context.resource_refs
        if resource.resource_type == "principal"
    ]
    return refs[0] if len(refs) == 1 else None


def tenant_memory_denied(
    host_context: HostContextEnvelope | None,
    resource_tenant: str,
) -> bool:
    """Memory tenant reads: the caller's namespace must match the tenant key."""
    namespace = tenant_namespace(host_context)
    if namespace is None:
        return False
    return namespace != resource_tenant


def memory_scope_denied(
    host_context: HostContextEnvelope | None,
    *,
    scope: str,
    resource_id: str,
) -> bool:
    """Bind USER Memory to the principal and TENANT Memory to the namespace."""
    authority_id = (
        _principal_ref(host_context) if scope == "user" else tenant_namespace(host_context)
    )
    # Internal/operator calls have no Host envelope. Once a Host envelope exists,
    # a missing or ambiguous authority key must fail closed just like Task access.
    return host_context is not None and authority_id != resource_id
