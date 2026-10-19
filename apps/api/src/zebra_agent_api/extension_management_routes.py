"""Dispatch optional protected extension operations without expanding API startup."""

from agent_core.application.plugin_installations import PluginInstallationService
from agent_core.ports.extensions import ExtensionStore
from agent_runtime.mcp_catalog_refresh import McpCatalogRefresh
from agent_security.mcp_credential_management import McpCredentialManagement
from agent_tools.skill_publications import SkillPublicationService
from fastapi import Request
from fastapi.responses import JSONResponse

from zebra_agent_api.extension_credentials import extension_credential_response
from zebra_agent_api.extension_reads import extension_read_response
from zebra_agent_api.mcp_catalog_refresh import catalog_refresh_response
from zebra_agent_api.plugin_installations import plugin_installation_response
from zebra_agent_api.skill_publications import skill_publication_response


async def extension_management_response(
    request: Request,
    *,
    service: McpCredentialManagement | None,
    refresh: McpCatalogRefresh | None,
    deployment: str,
    manage_enabled: bool,
    plugins: PluginInstallationService | None = None,
    plugins_enabled: bool = False,
    read_enabled: bool = True,
    extension_store: ExtensionStore | None = None,
    publications: SkillPublicationService | None = None,
) -> JSONResponse | None:
    result = await plugin_installation_response(
        request,
        service=plugins,
        deployment=deployment,
        enabled=plugins_enabled,
        read_enabled=read_enabled,
        manage_enabled=manage_enabled,
    )
    if result is not None:
        return result
    result = await catalog_refresh_response(
        request, service=refresh, deployment=deployment, manage_enabled=manage_enabled
    )
    if result is not None:
        return result
    result = await extension_credential_response(
        request, service=service, deployment=deployment, manage_enabled=manage_enabled
    )
    if result is not None:
        return result
    result = await skill_publication_response(
        request,
        service=publications,
        deployment=deployment,
        read_enabled=read_enabled,
        manage_enabled=manage_enabled,
    )
    if result is not None:
        return result
    return await extension_read_response(
        request,
        store=extension_store,
        deployment=deployment,
        manage_enabled=manage_enabled,
        publications=publications,
        mcp_catalogs=plugins.catalogs if plugins is not None and plugins.mcp_available else None,
        plugin_installations=plugins.store if plugins is not None else None,
    )
