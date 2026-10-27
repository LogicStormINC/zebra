"""Current native authority for a versioned, untrusted AG-UI Readable snapshot."""

from typing import Any
from uuid import UUID

from agent_core.domain.client_capabilities import FrontendCapabilityProfileVersion, ProfileLifecycle
from agent_core.domain.identifiers import TaskId

from zebra_agent_api.client_grant_auth import SessionBackedClientGrantAuthorizer
from zebra_agent_api.responses import ApiResponse
from zebra_agent_api.tenant_guard import task_access_response

_FIELDS = frozenset(
    {
        "clientStateVersion",
        "frontendAppId",
        "clientSessionId",
        "uiRevision",
        "profileDigest",
        "mountedSnapshotDigest",
        "clientBindingDigest",
    }
)


def bound_client_state_profile(
    app: Any, request: object | None, payload: dict[str, object], forwarded: dict[str, object]
) -> FrontendCapabilityProfileVersion | ApiResponse:
    """Read current scope facts; existing command CAS owns the subsequent commit."""
    if type(forwarded.get("clientStateVersion")) is not int or forwarded["clientStateVersion"] != 1:
        return _reject(400, "client_state_version_required")
    if set(forwarded) - _FIELDS:
        return _reject(400, "client_state_forwarded_fields_rejected")
    platform = getattr(app, "client_platform", None)
    sessions = getattr(platform, "client_sessions", None)
    profiles = getattr(platform, "frontend_capabilities", None)
    if sessions is None or profiles is None:
        return _reject(503, "client_state_unavailable")
    context = getattr(request, "host_context", None)
    verified = getattr(request, "verified_host_grant", None)
    cloud = getattr(getattr(app, "settings", None), "deployment", None) == "cloud"
    try:
        auth = SessionBackedClientGrantAuthorizer(sessions).authorize(
            getattr(request, "headers", None),
            host_context=context,
            require_host_context=cloud,
            verified_host_grant=verified,
        )
        if auth is None or str(auth.client_session_id) != forwarded.get("clientSessionId"):
            return _reject(401, "client_session_authorization_required")
        task = TaskId(UUID(str(payload.get("thread_id"))))
        run = payload.get("run_id")
        if not isinstance(run, str) or not run:
            return _reject(400, "client_state_run_required")
        denied = task_access_response(
            app,
            str(task),
            context,
            verified_host_grant=verified,
            run_id=run,
            required_scope="agent.run",
        )
        if denied is not None:
            return denied
        session = sessions.get_session(auth.client_session_id)
        if session is None:
            return _reject(401, "client_session_authorization_required")
        session.ensure_active()
        snapshot = sessions.get_mounted_snapshot(auth.client_session_id)
        binding = sessions.get_run_binding(task, run, auth.client_session_id)
        profile = profiles.get_profile_by_digest(
            session.grant.frontend_app_id, session.grant.profile_digest
        )
        if (
            not isinstance(profile, FrontendCapabilityProfileVersion)
            or profile.lifecycle is not ProfileLifecycle.PUBLISHED
        ):
            return _reject(409, "client_state_profile_inactive")
        if context is not None:
            current = profiles.get_binding_for_host(
                context.host_app_id, context.namespace_id, session.grant.frontend_app_id
            )
            if current is None or current.profile_digest != profile.profile_digest:
                return _reject(403, "client_state_profile_not_bound")
        if snapshot is None or binding is None:
            return _reject(409, "client_state_surface_required")
        revision = forwarded.get("uiRevision")
        if (
            type(revision) is not int
            or revision != snapshot.ui_revision
            or revision != session.ui_revision
            or forwarded.get("frontendAppId") != session.grant.frontend_app_id
            or forwarded.get("profileDigest") != profile.profile_digest
            or profile.profile_digest != session.grant.profile_digest
            or snapshot.profile_revision != profile.revision
            or binding.task_id != task
            or binding.run_id != run
            or binding.client_session_id != auth.client_session_id
            or snapshot.profile_digest != profile.profile_digest
            or binding.profile_digest != profile.profile_digest
            or snapshot.frontend_app_id != profile.frontend_app_id
            or session.mounted_snapshot_digest != snapshot.snapshot_digest
            or binding.mounted_snapshot_digest != snapshot.snapshot_digest
            or forwarded.get("mountedSnapshotDigest") != snapshot.snapshot_digest
            or forwarded.get("clientBindingDigest") != binding.binding_digest
        ):
            return _reject(409, "client_state_surface_changed")
        source = payload.get("input")
        source = source if isinstance(source, dict) else {}
        state = source.get("state")
        tools = source.get("tools") or []
        if not isinstance(state, dict) or not isinstance(tools, list):
            return _reject(400, "client_state_payload_invalid")
        if set(state) - set(snapshot.mounted_readables):
            return _reject(422, "client_state_readable_not_mounted")
        names = [tool.get("name") if isinstance(tool, dict) else None for tool in tools]
        if any(not isinstance(name, str) for name in names):
            return _reject(422, "client_state_tool_invalid")
        if set(names) - (set(snapshot.mounted_actions) & set(binding.allowed_actions)):
            return _reject(422, "client_state_tool_not_bound")
        return profile
    except (TypeError, ValueError):
        return _reject(400, "client_state_metadata_invalid")
    except Exception:
        return _reject(503, "client_state_unavailable")


def _reject(status: int, reason: str) -> ApiResponse:
    return ApiResponse(status, {"status": reason, "reason": reason})
