"""Bounded, scoped skill installation and HTTP MCP configuration creation."""

from agent_core.application.mcp_connections import create_mcp_connection
from agent_core.application.skill_installations import create_skill_installation
from agent_core.domain.extensions import SkillInstallation
from agent_core.ports.extensions import (
    ExtensionNotFoundError,
    ExtensionRevisionConflictError,
    ExtensionStore,
)
from agent_security.extension_authority import extension_scope_from_grant
from agent_security.host_grant import HostGrantSecurityError, VerifiedHostGrant
from fastapi import Request
from fastapi.responses import JSONResponse
from pydantic import ValidationError

from zebra_agent_api.extension_reads import _public_record, extension_error
from zebra_agent_api.extension_request_body import ExtensionBodyTooLarge, extension_request_body


async def extension_create_response(
    request: Request, *, store: ExtensionStore, verified: VerifiedHostGrant,
    collection: str = "mcp-connections",
) -> JSONResponse:
    try:
        scope = extension_scope_from_grant(verified, permission="extensions.manage")
    except HostGrantSecurityError:
        return extension_error(403)
    keys = request.headers.getlist("idempotency-key")
    if request.query_params or len(keys) != 1:
        return extension_error(422)
    try:
        payload = await extension_request_body(request)
    except ExtensionBodyTooLarge:
        return extension_error(413)
    except (ValueError, RecursionError):
        return extension_error(422)
    try:
        create = (create_skill_installation if collection == "skill-installations"
                  else create_mcp_connection)
        record, created = await create(
            store=store, scope=scope, idempotency_key=keys[0], payload=payload,
        )
    except ValidationError:
        return extension_error(422)
    except ExtensionNotFoundError:
        return extension_error(404)
    except ExtensionRevisionConflictError:
        return extension_error(409)
    except Exception:
        return extension_error(503)
    identifier = (record.installation_id if isinstance(record, SkillInstallation)
                  else record.connection_id)
    return JSONResponse(
        status_code=201 if created else 200, content=_public_record(record),
        headers={"Cache-Control": "no-store", "ETag": f'"{record.revision}"',
                 "Location": f"/v1/extensions/{collection}/{identifier}"},
    )
