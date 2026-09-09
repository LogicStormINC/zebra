"""Bounded enabled-only PATCH adapter for existing scoped configuration."""

import re

from agent_core.application.extension_configuration import set_extension_enabled
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

from zebra_agent_api.extension_reads import _ID, _public_record, extension_error
from zebra_agent_api.extension_request_body import ExtensionBodyTooLarge, extension_request_body


async def extension_update_response(
    request: Request, *, store: ExtensionStore, verified: VerifiedHostGrant,
    collection: str, object_id: str,
) -> JSONResponse:
    try:
        scope = extension_scope_from_grant(verified, permission="extensions.manage")
    except HostGrantSecurityError:
        return extension_error(403)
    if request.query_params:
        return extension_error(422)
    matches = request.headers.getlist("if-match")
    if not matches:
        return extension_error(428)
    if len(matches) != 1 or re.fullmatch(r'"[1-9][0-9]*"', matches[0]) is None:
        return extension_error(422)
    try:
        expected_revision = int(matches[0][1:-1])
        _ID.validate_python(object_id)
        payload = await extension_request_body(request)
        if not isinstance(payload, dict) or set(payload) != {"enabled"}:
            return extension_error(422)
        if type(payload["enabled"]) is not bool:
            return extension_error(422)
    except ExtensionBodyTooLarge:
        return extension_error(413)
    except (ValueError, ValidationError, RecursionError):
        return extension_error(422)
    try:
        record = await set_extension_enabled(
            store=store, scope=scope,
            kind="skill" if collection == "skill-installations" else "mcp",
            object_id=object_id, expected_revision=expected_revision, enabled=payload["enabled"],
        )
    except ExtensionNotFoundError:
        return extension_error(404)
    except ExtensionRevisionConflictError:
        return extension_error(409)
    except Exception:
        return extension_error(503)
    return JSONResponse(
        content=_public_record(record),
        headers={"Cache-Control": "no-store", "ETag": f'"{record.revision}"'},
    )
