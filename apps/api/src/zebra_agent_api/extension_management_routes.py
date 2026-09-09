"""Dispatch optional protected extension operations without expanding API startup."""

from agent_runtime.mcp_catalog_refresh import McpCatalogRefresh
from agent_security.mcp_credential_management import McpCredentialManagement
from fastapi import Request
from fastapi.responses import JSONResponse

from zebra_agent_api.extension_credentials import extension_credential_response
from zebra_agent_api.mcp_catalog_refresh import catalog_refresh_response


async def extension_management_response(
    request: Request,
    *,
    service: McpCredentialManagement | None,
    refresh: McpCatalogRefresh | None,
    deployment: str,
    manage_enabled: bool,
) -> JSONResponse | None:
    result = await catalog_refresh_response(
        request, service=refresh, deployment=deployment, manage_enabled=manage_enabled
    )
    if result is not None:
        return result
    return await extension_credential_response(
        request, service=service, deployment=deployment, manage_enabled=manage_enabled
    )
