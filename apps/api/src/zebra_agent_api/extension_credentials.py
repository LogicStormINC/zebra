"""Secret-write/revoke adapter; never return ciphertext or plaintext credentials."""

import re

from agent_core.domain.mcp_credentials import McpCredentialProtectionError
from agent_core.ports.extensions import ExtensionNotFoundError, ExtensionRevisionConflictError
from agent_security.extension_authority import extension_scope_from_grant
from agent_security.host_grant import HostGrantSecurityError, VerifiedHostGrant
from agent_security.mcp_credential_management import McpCredentialManagement
from fastapi import Request
from fastapi.responses import JSONResponse

from zebra_agent_api.extension_reads import _ID, _public_record, extension_error
from zebra_agent_api.extension_request_body import ExtensionBodyTooLarge, extension_request_body


async def extension_credential_response(
    request: Request,
    *,
    service: McpCredentialManagement | None,
    deployment: str,
    manage_enabled: bool,
) -> JSONResponse | None:
    parts = request.url.path.split("/")
    if (
        len(parts) != 6
        or parts[1:4] != ["v1", "extensions", "mcp-connections"]
        or parts[5] != "credentials"
    ):
        return None
    if service is None or deployment == "local" or not manage_enabled:
        return extension_error(404)
    verified = getattr(request.state, "verified_host_grant", None)
    if not isinstance(verified, VerifiedHostGrant):
        return extension_error(403)
    try:
        scope = extension_scope_from_grant(verified, permission="extensions.manage")
    except HostGrantSecurityError:
        return extension_error(403)
    if request.method not in ("POST", "DELETE"):
        return extension_error(405, allow="POST, DELETE")
    if request.query_params:
        return extension_error(422)
    matches = request.headers.getlist("if-match")
    if not matches:
        return extension_error(428)
    if len(matches) != 1 or re.fullmatch(r'"[1-9][0-9]{0,18}"', matches[0]) is None:
        return extension_error(422)
    try:
        connection_id = _ID.validate_python(parts[4])
        revision = int(matches[0][1:-1])
        if request.method == "POST":
            body = await extension_request_body(request)
            if (
                not isinstance(body, dict)
                or set(body) != {"token"}
                or not isinstance(body["token"], str)
            ):
                return extension_error(422)
            token = body["token"]
            if not token or any(not 0x21 <= ord(char) <= 0x7E for char in token):
                return extension_error(422)
        else:
            async for chunk in request.stream():
                if chunk:
                    return extension_error(422)
    except ExtensionBodyTooLarge:
        return extension_error(413)
    except (ValueError, RecursionError):
        return extension_error(422)
    try:
        if request.method == "POST":
            record = await service.provision(
                verified=verified,
                connection_id=connection_id,
                expected_connection_revision=revision,
                token=token,
            )
        else:
            record = await service.revoke(
                verified=verified,
                connection_id=connection_id,
                expected_connection_revision=revision,
            )
        if record.scope != scope or record.connection_id != connection_id:
            return extension_error(404)
    except HostGrantSecurityError:
        return extension_error(403)
    except ExtensionNotFoundError:
        return extension_error(404)
    except ExtensionRevisionConflictError:
        return extension_error(409)
    except McpCredentialProtectionError:
        return extension_error(503)
    except ValueError:
        return extension_error(422)
    except Exception:
        return extension_error(503)
    return JSONResponse(
        content=_public_record(record),
        headers={"Cache-Control": "no-store", "ETag": f'"{record.revision}"'},
    )
