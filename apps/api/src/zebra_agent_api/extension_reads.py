"""Opt-in asynchronous reads of scoped extension configuration; no execution."""

from agent_core.domain.extensions import McpConnection, OpaqueExtensionId, SkillInstallation
from agent_core.ports.extensions import (
    ExtensionNotFoundError,
    ExtensionPageRequest,
    ExtensionStore,
)
from agent_security.extension_authority import extension_scope_from_grant
from agent_security.host_grant import HostGrantSecurityError, VerifiedHostGrant
from fastapi import Request
from fastapi.responses import JSONResponse
from pydantic import TypeAdapter, ValidationError

_PREFIX = "/v1/extensions"
_ID = TypeAdapter(OpaqueExtensionId)
_ERRORS = {
    401: ("authorization_required", "A verified Host Grant is required."),
    403: ("permission_denied", "Extension access is not permitted."),
    404: ("not_found", "Extension configuration was not found."),
    405: ("method_not_allowed", "Only GET is supported."),
    409: ("revision_conflict", "Extension revision has changed."),
    413: ("request_too_large", "Extension request body is too large."),
    422: ("invalid_request", "Extension request is invalid."),
    428: ("precondition_required", "If-Match is required."),
    503: ("service_unavailable", "Extension configuration is temporarily unavailable."),
}


def is_extension_path(path: str) -> bool:
    return path == _PREFIX or path.startswith(_PREFIX + "/")


def extension_error(status: int, *, allow: str = "GET") -> JSONResponse:
    code, message = _ERRORS[status]
    headers = {"Cache-Control": "no-store"}
    if status == 405:
        headers["Allow"] = allow
        if allow != "GET":
            message = f"Supported methods: {allow}."
    return JSONResponse(
        status_code=status,
        content={"code": code, "message": message, "retryable": status == 503, "action": None},
        headers=headers,
    )


def _public_record(record: SkillInstallation | McpConnection) -> dict[str, object]:
    if isinstance(record, SkillInstallation):
        return {
            "installation_id": record.installation_id,
            "revision": record.revision,
            "enabled": record.enabled,
            "version": {
                "skill_id": record.version.skill_id,
                "version_id": record.version.version_id,
                "content_digest": record.version.content_digest,
            },
        }
    return {
        "connection_id": record.connection_id,
        "revision": record.revision,
        "transport": record.transport,
        "endpoint": record.endpoint,
        "auth_mode": record.auth_mode.value,
        "auth_state": record.auth_state.value,
        "enabled": record.enabled,
    }


async def extension_read_response(
    request: Request, *, store: ExtensionStore | None, deployment: str,
    manage_enabled: bool = False,
) -> JSONResponse | None:
    if not is_extension_path(request.url.path):
        return None
    if store is None or deployment == "local":
        return extension_error(404)
    parts = request.url.path.removeprefix(_PREFIX + "/").split("/")
    if (
        len(parts) not in (1, 2)
        or parts[0] not in ("skill-installations", "mcp-connections")
        or not all(parts)
    ):
        return extension_error(404)
    verified = getattr(request.state, "verified_host_grant", None)
    if not isinstance(verified, VerifiedHostGrant):
        return extension_error(403)
    if manage_enabled and len(parts) == 1 and request.method == "POST":
        from zebra_agent_api.extension_creates import extension_create_response

        return await extension_create_response(
            request, store=store, verified=verified, collection=parts[0],
        )
    if manage_enabled and len(parts) == 2 and request.method == "PATCH":
        from zebra_agent_api.extension_updates import extension_update_response

        return await extension_update_response(
            request, store=store, verified=verified, collection=parts[0], object_id=parts[1],
        )
    try:
        scope = extension_scope_from_grant(verified, permission="extensions.read")
    except HostGrantSecurityError:
        return extension_error(403)
    if request.method != "GET":
        allow = "GET, PATCH" if manage_enabled and len(parts) == 2 else "GET"
        if manage_enabled and len(parts) == 1:
            allow = "GET, POST"
        return extension_error(405, allow=allow)
    query = request.query_params
    if (
        len(query.multi_items()) != len(query)
        or set(query) - {"limit", "cursor"}
        or (len(parts) == 2 and query)
    ):
        return extension_error(422)
    try:
        if len(parts) == 2:
            _ID.validate_python(parts[1])
        page = ExtensionPageRequest(limit=int(query.get("limit", "50")), cursor=query.get("cursor"))
    except (ValueError, ValidationError):
        return extension_error(422)
    try:
        skills = parts[0] == "skill-installations"
        if len(parts) == 2:
            record = (
                await store.get_skill(scope=scope, installation_id=parts[1])
                if skills
                else await store.get_mcp(scope=scope, connection_id=parts[1])
            )
            if record.scope != scope:
                return extension_error(404)
            content = _public_record(record)
        else:
            records = (
                await store.list_skills(scope=scope, page=page)
                if skills
                else await store.list_mcp(scope=scope, page=page)
            )
            if any(record.scope != scope for record in records.items):
                return extension_error(404)
            content = {
                "items": [_public_record(record) for record in records.items],
                "next_cursor": records.next_cursor,
            }
    except ExtensionNotFoundError:
        return extension_error(404)
    except Exception:
        # Cancellation derives from BaseException and must reach the server.
        return extension_error(503)
    headers = {"Cache-Control": "no-store"}
    if len(parts) == 2:
        headers["ETag"] = f'"{record.revision}"'
    return JSONResponse(content=content, headers=headers)
