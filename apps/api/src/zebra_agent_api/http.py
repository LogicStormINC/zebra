from __future__ import annotations

import asyncio
from collections.abc import Mapping
from pathlib import Path

from agent_core.application.agent_definitions import PublisherGrantPort
from agent_core.application.plugin_installations import PluginInstallationService
from agent_core.ports.agent_registry import AgentRegistryPort
from agent_core.ports.event_store import BoundedSessionEventReadPort
from agent_core.ports.extensions import ExtensionStore
from agent_integrations import GitHubPullRequestTransport
from agent_runtime.mcp_catalog_refresh import McpCatalogRefresh
from agent_security import CredentialBroker
from agent_security.mcp_credential_management import McpCredentialManagement
from agent_storage import CloudCompositionSettings, ControlPlaneStores, PostgresControlPlaneStores
from agent_storage.postgres.stream_proof_batch import StreamProofSnapshot
from agent_storage.postgres.task_io import TaskIoConnections
from agent_tools.skill_publications import SkillPublicationService
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, Response, StreamingResponse
from zebra_agent_config import ZebraAgentSettings, load_settings

from zebra_agent_api.ag_ui_task_view import authorized_async_read, authorized_task_preflight
from zebra_agent_api.app import create_app
from zebra_agent_api.artifact_download import (
    artifact_download_response,
    authorized_artifact_read,
)
from zebra_agent_api.coverage_public_read import cloud_raw_stream_preflight
from zebra_agent_api.coverage_report_http import coverage_report_response
from zebra_agent_api.extension_composition import (
    compose_http_extensions,
    compose_http_turn_admission,
    resolve_publication_cloud,
)
from zebra_agent_api.extension_management_routes import extension_management_response
from zebra_agent_api.extension_reads import (
    extension_error,
    is_extension_path,
)
from zebra_agent_api.health_readiness import ApiHealth
from zebra_agent_api.host_registry_management import deployment_namespace as _deployment_namespace
from zebra_agent_api.host_registry_management import register_management_routes
from zebra_agent_api.http_host_auth import (
    HostGrantHttpRequest as HostGrantHttpRequest,
)
from zebra_agent_api.http_host_auth import (
    HostGrantRequestAuthorizer as HostGrantRequestAuthorizer,
)
from zebra_agent_api.http_host_auth import (
    _resolve_host_origins,
    authorize_request,
    read_authorized_body,
)
from zebra_agent_api.http_origins import _normalize_exact_origin as _normalize_exact_origin
from zebra_agent_api.http_stream_routing import (
    _is_agui_stream_request,
    _is_stream_request,
    _stream_resource_id,
)
from zebra_agent_api.publication_management import register_publication_management
from zebra_agent_api.request_cursor import after_sequence
from zebra_agent_api.responses import ApiResponse
from zebra_agent_api.routes import RouteAdapter, RouteRequest
from zebra_agent_api.session_identity_read import _parse_session_id
from zebra_agent_api.session_streaming import tail_session_events, tail_task_events
from zebra_agent_api.task_api import parse_task_id
from zebra_agent_api.tenant_guard import tenant_scope_response

HTTP_METHODS = ["DELETE", "GET", "HEAD", "OPTIONS", "PATCH", "POST", "PUT"]
HTTP_ALLOWED_HEADERS = [
    "Accept",
    "Authorization",
    "Content-Type",
    "Last-Event-ID",
    "X-Zebra-Client-Fence",
    "X-Zebra-Client-Session",
]


def create_http_app(
    database_path: str | Path | None = None,
    *,
    settings: ZebraAgentSettings | None = None,
    stores: ControlPlaneStores | None = None,
    cloud_composition: CloudCompositionSettings | None = None,
    administrative_context_namespace: str | None = None,
    context_administrative_namespace: str | None = None,
    credential_broker: CredentialBroker | None = None,
    credential_env: Mapping[str, str] | None = None,
    github_transport: GitHubPullRequestTransport | None = None,
    host_grant_authorizer: HostGrantRequestAuthorizer | None = None,
    host_grant_origins: tuple[str, ...] | None = None,
    extension_store: ExtensionStore | None = None,
    skill_publication_service: SkillPublicationService | None = None,
    mcp_credential_management: McpCredentialManagement | None = None,
    mcp_catalog_refresh: McpCatalogRefresh | None = None,
    plugin_installation_service: PluginInstallationService | None = None,
    agent_registry: AgentRegistryPort | None = None,
    publisher_grants: PublisherGrantPort | None = None,
) -> FastAPI:
    active_settings = settings or load_settings()
    active_database_path = Path(database_path or active_settings.database_url)
    cloud_composition = resolve_publication_cloud(
        active_settings,
        stores,
        cloud_composition,
        extension_store,
        skill_publication_service,
        mcp_credential_management,
        mcp_catalog_refresh,
        plugin_installation_service,
    )
    api = create_app(
        active_database_path,
        settings=active_settings,
        stores=stores,
        cloud_composition=cloud_composition,
        administrative_context_namespace=administrative_context_namespace,
        context_administrative_namespace=context_administrative_namespace,
        credential_broker=credential_broker,
        credential_env=credential_env,
        github_transport=github_transport,
        agent_registry=agent_registry,
        publisher_grants=publisher_grants,
    )
    task_io_connections = None
    if (
        active_settings.deployment != "local"
        and (
            host_grant_authorizer is None
            or active_settings.cloud_extensions_read_enabled
            and extension_store is None
        )
        and isinstance(api.stores, PostgresControlPlaneStores)
    ):
        # All default cloud reads share addresses, never connections or authority.
        # Explicit adapters stay owned by their caller; local composition is unchanged.
        task_io_connections = api.stores.task_io_connections
        if task_io_connections is None:
            task_io_connections = TaskIoConnections(
                cloud_composition.dsn
                if cloud_composition is not None
                else active_settings.database_url
            )
    (
        active_extension_store,
        skill_publication_service,
        mcp_credential_management,
        mcp_catalog_refresh,
    ) = compose_http_extensions(
        active_settings,
        api,
        service=skill_publication_service,
        cloud_composition=cloud_composition,
        extension_store=extension_store,
        credentials=mcp_credential_management,
        refresh=mcp_catalog_refresh,
        task_io_connections=task_io_connections,
    )
    active_host_grant_authorizer = host_grant_authorizer
    if active_host_grant_authorizer is None and active_settings.deployment != "local":
        active_host_grant_authorizer = _compose_production_host_grant_authorizer(
            active_settings,
            api.stores,
            cloud_composition=cloud_composition,
            task_io_connections=task_io_connections,
        )
    from zebra_agent_api.plugin_composition import compose_plugins

    plugin_installation_service, plugin_resolver = compose_plugins(
        active_settings,
        cloud_composition,
        active_extension_store,
        plugin_installation_service,
        task_io_connections=task_io_connections,
    )
    turn_admission = compose_http_turn_admission(
        active_settings,
        api,
        active_extension_store,
        cloud_composition=cloud_composition,
        plugins=plugin_resolver,
    )
    adapter = RouteAdapter(api, turn_admission)
    exact_host_origins = _resolve_host_origins(
        active_host_grant_authorizer,
        host_grant_origins,
    )
    health = ApiHealth(api, active_host_grant_authorizer)
    app = FastAPI(title="Zebra Agent API", lifespan=health.lifespan)
    health.register(app)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"] if active_settings.deployment == "local" else exact_host_origins,
        allow_methods=HTTP_METHODS,
        allow_headers=[*HTTP_ALLOWED_HEADERS, "If-Match", "Idempotency-Key"],
        expose_headers=["ETag", "X-Coverage-Report-Sha256", "Content-Disposition"],
        allow_credentials=False,
    )

    async def optional_extensions(request: Request) -> Response | None:
        return await extension_management_response(
            request,
            service=mcp_credential_management,
            refresh=mcp_catalog_refresh,
            deployment=active_settings.deployment,
            manage_enabled=active_settings.cloud_extensions_manage_enabled,
            read_enabled=active_settings.cloud_extensions_read_enabled,
            extension_store=active_extension_store,
            publications=skill_publication_service,
            plugins=plugin_installation_service,
            plugins_enabled=active_settings.plugins.enabled,
        )

    async def handle(request: Request, full_path: str = "") -> Response:
        if request.method.upper() == "OPTIONS" and not is_extension_path(request.url.path):
            return Response(status_code=200)
        auth_error = await authorize_request(
            request,
            active_settings,
            api=api,
            host_grant_authorizer=active_host_grant_authorizer,
            host_grant_origins=exact_host_origins,
        )
        if auth_error is not None:
            if is_extension_path(request.url.path):
                return extension_error(auth_error.status_code)
            return auth_error
        if (
            active_settings.deployment != "local"
            and request.method == "GET"
            and is_extension_path(request.url.path)
        ):
            extension_response = await authorized_async_read(
                lambda: optional_extensions(request),
                authorization_expires_at=getattr(
                    getattr(request.state, "host_context", None), "expires_at", None
                ),
                request_deadline=getattr(request.state, "authorization_deadline", None),
            )
            if isinstance(extension_response, ApiResponse):
                return extension_error(extension_response.status_code)
        else:
            extension_response = await optional_extensions(request)
        if extension_response is not None:
            return extension_response
        report_response = await coverage_report_response(request, adapter)
        if report_response is not None:
            return report_response
        download_response = await artifact_download_response(request, adapter)
        if download_response is not None:
            return download_response
        body, body_error = await read_authorized_body(request, api, active_host_grant_authorizer)
        if body_error is not None:
            return body_error
        if _is_agui_stream_request(request):
            from zebra_agent_api.stream_v2_http import agui_response

            if stream_response := await agui_response(api, request, body=body):
                return stream_response
        state = request.state
        route_request = RouteRequest(
            method=request.method,
            path=request.url.path,
            body=body,
            headers=dict(request.headers),
            query=dict(request.query_params),
            host_context=getattr(state, "host_context", None),
            verified_host_grant=getattr(state, "verified_host_grant", None),
            previous_host_context=getattr(state, "previous_host_context", None),
            previous_verified_host_grant=getattr(state, "previous_verified_host_grant", None),
        )
        artifact_parts = tuple(part for part in request.url.path.split("/") if part)
        raw_negotiated = False
        if (
            active_settings.deployment != "local"
            and request.method == "GET"
            and len(artifact_parts) == 5
            and artifact_parts[0] in {"tasks", "sessions"}
            and artifact_parts[2] == "artifacts"
            and artifact_parts[4] == "content"
        ):
            response = await authorized_artifact_read(request, adapter, route_request)
        elif active_settings.deployment != "local" and _is_stream_request(request):
            from zebra_agent_api.stream_v2_http import raw_response

            def preflight(proof: StreamProofSnapshot | None = None) -> ApiResponse | None:
                denied = (
                    tenant_scope_response(api, route_request, proof=proof)
                    if proof is not None
                    else tenant_scope_response(api, route_request)
                )
                if denied is not None:
                    return denied
                source = (
                    cloud_raw_stream_preflight(api.stores, request.url.path, proof=proof)
                    if proof is not None
                    else cloud_raw_stream_preflight(api.stores, request.url.path)
                )
                return source if source.status_code != 200 else None

            v2_response = await raw_response(
                api,
                request,
                database_path=active_database_path,
                preflight=preflight,
                snapshot_preflight=preflight,
            )
            if v2_response is not None:
                return v2_response
            raw_negotiated = True
            response = ApiResponse(200, {})
        elif (
            active_settings.deployment != "local"
            and request.url.path.endswith("/stream")
            and not _is_agui_stream_request(request)
        ):
            response = ApiResponse(404, {"status": "not_found"})
        elif active_settings.deployment != "local" and request.method in {"GET", "HEAD"}:
            response = await authorized_task_preflight(
                lambda: None,
                lambda: adapter.handle(route_request),
                authorization_expires_at=getattr(route_request.host_context, "expires_at", None),
                request_deadline=getattr(request.state, "authorization_deadline", None),
            )
        else:
            # Observation budgets must not turn an uncertain command into a retry.
            response = await asyncio.to_thread(adapter.handle, route_request)
        if _is_stream_request(request) and response.status_code == 200:
            from zebra_agent_api.stream_v2_http import raw_response

            if not raw_negotiated:
                v2_response = await raw_response(api, request, database_path=active_database_path)
                if v2_response is not None:
                    return v2_response
            stream_id = _stream_resource_id(request.url.path)
            after_sequence_value, cursor_error = after_sequence(request)
            if cursor_error is not None:
                return cursor_error
            if request.url.path.startswith("/tasks/"):
                task_key = parse_task_id(stream_id)
                if isinstance(task_key, ApiResponse):
                    return JSONResponse(
                        status_code=task_key.status_code,
                        content=task_key.body,
                    )
                head = await authorized_task_preflight(
                    lambda: None,
                    lambda: api.stores.tasks.read_task_header(
                        task_key, require_source_coverage=active_settings.deployment != "local"
                    ),
                    authorization_expires_at=getattr(
                        route_request.host_context, "expires_at", None
                    ),
                    request_deadline=getattr(request.state, "authorization_deadline", None),
                )
                if isinstance(head, ApiResponse):
                    return JSONResponse(status_code=head.status_code, content=head.body)
                if head is None:
                    return JSONResponse(status_code=404, content={"status": "not_found"})
                if after_sequence_value > head.current_sequence:
                    return JSONResponse(
                        status_code=400,
                        content={
                            "status": "invalid_request",
                            "reason": "after_sequence exceeds Task highwater",
                        },
                    )
                stream = tail_task_events(
                    database_path=active_database_path,
                    stores=api.stores,
                    task_id=task_key,
                    live_event_fanout=api.live_event_fanout,
                    notifications=api.stream_notifications,
                    deployment_namespace=_deployment_namespace(api),
                    authorization_expires_at=getattr(
                        route_request.host_context, "expires_at", None
                    ),
                    request=request,
                    after_sequence=after_sequence_value,
                )
            else:
                session_key = _parse_session_id(stream_id)
                if isinstance(session_key, ApiResponse):
                    return JSONResponse(
                        status_code=session_key.status_code,
                        content=session_key.body,
                    )
                if active_settings.deployment != "local":
                    if not isinstance(api.stores.events, BoundedSessionEventReadPort):
                        return JSONResponse(status_code=503, content={"status": "unavailable"})
                    event_reader = api.stores.events
                    highwater = await authorized_task_preflight(
                        lambda: None,
                        lambda: event_reader.read_session_highwater(session_key),
                        authorization_expires_at=getattr(
                            route_request.host_context, "expires_at", None
                        ),
                        request_deadline=getattr(request.state, "authorization_deadline", None),
                    )
                    if isinstance(highwater, ApiResponse):
                        return JSONResponse(
                            status_code=highwater.status_code, content=highwater.body
                        )
                    if after_sequence_value > highwater:
                        return JSONResponse(
                            status_code=400,
                            content={
                                "status": "invalid_request",
                                "reason": "after_sequence exceeds Session highwater",
                            },
                        )
                stream = tail_session_events(
                    database_path=active_database_path,
                    stores=api.stores,
                    live_event_fanout=api.live_event_fanout,
                    notifications=api.stream_notifications,
                    deployment_namespace=_deployment_namespace(api),
                    session_id=session_key,
                    authorization_expires_at=getattr(
                        route_request.host_context, "expires_at", None
                    ),
                    request=request,
                    after_sequence=after_sequence_value,
                )
            return StreamingResponse(
                stream,
                media_type="text/event-stream",
                headers={
                    "Cache-Control": "no-cache",
                    "X-Accel-Buffering": "no",
                },
            )
        return JSONResponse(status_code=response.status_code, content=response.body)

    async def handle_artifact_preview_head(
        request: Request,
        task_id: str,
        artifact_id: str,
    ) -> Response:
        _ = task_id, artifact_id
        return await handle(request)

    register_publication_management(app, active_settings, api, cloud_composition)
    register_management_routes(
        app, active_settings, lambda: _deployment_namespace(api), cloud_composition
    )
    app.add_api_route("/", handle, methods=HTTP_METHODS, response_model=None)
    app.add_api_route(
        "/tasks/{task_id}/artifacts/{artifact_id}/preview",
        handle_artifact_preview_head,
        methods=["HEAD"],
        response_model=None,
    )
    app.add_api_route(
        "/v1/extensions", handle, methods=["HEAD", "TRACE", "CONNECT"], response_model=None
    )
    app.add_api_route(
        "/v1/extensions/{full_path:path}",
        handle,
        methods=["HEAD", "TRACE", "CONNECT"],
        response_model=None,
    )
    app.add_api_route("/{full_path:path}", handle, methods=HTTP_METHODS, response_model=None)
    return app


def _compose_production_host_grant_authorizer(
    settings: ZebraAgentSettings,
    stores: ControlPlaneStores,
    *,
    cloud_composition: CloudCompositionSettings | None,
    task_io_connections: TaskIoConnections | None = None,
) -> HostGrantRequestAuthorizer | None:
    """Build the default cloud authorizer only for the PostgreSQL composition."""
    if not isinstance(stores, PostgresControlPlaneStores):
        return None
    from zebra_agent_api.host_auth import build_postgres_host_grant_authorizer

    return build_postgres_host_grant_authorizer(
        cloud_composition.dsn if cloud_composition is not None else settings.database_url,
        deployment_namespace=stores.deployment_namespace,
        **({"task_io_connections": task_io_connections} if task_io_connections is not None else {}),
    )
