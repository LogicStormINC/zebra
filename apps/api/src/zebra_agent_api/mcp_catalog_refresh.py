"""Protected catalog refresh; request bodies cannot supply URLs or credentials."""

import json
import logging
import re

from agent_core.domain.mcp_credentials import McpCredentialProtectionError
from agent_core.ports.extensions import ExtensionNotFoundError, ExtensionRevisionConflictError
from agent_core.ports.mcp_catalog import McpCatalogIntegrityError
from agent_runtime.mcp_catalog_refresh import McpCatalogRefresh
from agent_runtime.mcp_protocol import McpProtocolError
from agent_security.extension_authority import extension_scope_from_grant
from agent_security.host_grant import HostGrantSecurityError, VerifiedHostGrant
from fastapi import Request
from fastapi.responses import JSONResponse

from zebra_agent_api.extension_reads import _ID, extension_error


async def catalog_refresh_response(
    request: Request, *, service: McpCatalogRefresh | None, deployment: str, manage_enabled: bool
) -> JSONResponse | None:
    parts = request.url.path.split("/")
    if (
        len(parts) != 6
        or parts[1:4] != ["v1", "extensions", "mcp-connections"]
        or parts[5] not in ("refresh", "catalog")
    ):
        return None
    if service is None or deployment == "local" or not manage_enabled:
        return extension_error(404)
    verified = getattr(request.state, "verified_host_grant", None)
    reading = parts[5] == "catalog"
    method = "GET" if reading else "POST"
    try:
        if not isinstance(verified, VerifiedHostGrant):
            return extension_error(403)
        scope = extension_scope_from_grant(
            verified, permission="extensions.read" if reading else "extensions.manage"
        )
    except HostGrantSecurityError:
        return extension_error(403)
    if request.method != method:
        return extension_error(405, allow=method)
    values = request.headers.getlist("if-match")
    if not reading and not values:
        return extension_error(428)
    if (
        request.query_params
        or (reading and bool(values))
        or (
            not reading
            and (len(values) != 1 or re.fullmatch(r'"[1-9][0-9]{0,18}"', values[0]) is None)
        )
    ):
        return extension_error(422)
    async for chunk in request.stream():
        if chunk:
            return extension_error(422)
    try:
        identifier = _ID.validate_python(parts[4])
        if reading:
            catalog = await service.read(verified=verified, connection_id=identifier)
            revision = catalog.connection.revision
        else:
            revision = int(values[0][1:-1])
            catalog = await service.refresh(
                verified=verified, connection_id=identifier, expected_revision=revision
            )
        if (
            catalog.connection.scope != scope
            or catalog.connection.connection_id != identifier
            or catalog.connection.revision != revision
        ):
            return extension_error(404)
    except HostGrantSecurityError:
        return extension_error(403)
    except ExtensionNotFoundError:
        return extension_error(404)
    except ExtensionRevisionConflictError:
        return extension_error(409)
    except (McpProtocolError, McpCredentialProtectionError, McpCatalogIntegrityError) as exc:
        logging.getLogger(__name__).warning("MCP catalog unavailable: %s", type(exc).__name__)
        return extension_error(503)
    except ValueError:
        return extension_error(422)
    except Exception as exc:
        logging.getLogger(__name__).warning("MCP catalog failed: %s", type(exc).__name__)
        return extension_error(503)
    return JSONResponse(
        {
            "connection_id": identifier,
            "config_revision": revision,
            "catalog_digest": catalog.digest,
            "tool_count": len(catalog.tools),
            **(
                {
                    "tools": [
                        {
                            "name": tool.name,
                            "description": tool.description,
                            "input_schema": json.loads(tool.input_schema_json),
                        }
                        for tool in catalog.tools
                    ]
                }
                if reading
                else {}
            ),
        },
        headers={"Cache-Control": "no-store", "ETag": f'"{revision}"'},
    )
