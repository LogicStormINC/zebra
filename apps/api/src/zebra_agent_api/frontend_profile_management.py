"""Product/Host/App-scoped Profile management, never a platform operator credential."""

from functools import partial
from typing import Any

from agent_control_plane.frontend_profiles import (
    FrontendProfileService,
    FrontendProfileServiceError,
)
from agent_core.domain.client_capabilities import ClientCapabilityError
from agent_storage.postgres.client_capabilities import PostgresClientCapabilityRegistry
from agent_storage.postgres.frontend_profile_management import FrontendProfileManagementStore
from agent_storage.postgres.host_management import (
    HostManagementConflict,
    HostManagementExpired,
    HostManagementUnavailable,
)
from fastapi import FastAPI
from fastapi.responses import JSONResponse
from zebra_agent_config import ZebraAgentSettings

from zebra_agent_api.host_registry_config import load_host_management_config
from zebra_agent_api.management_transport import authorize_management, register_management_endpoint
from zebra_agent_api.runtime_management import _error

PATH = "/management/v1/host-frontend-profile"


def _perform(
    settings: ZebraAgentSettings,
    namespace: str | None,
    token: str,
    headers: dict[str, list[str]],
    method: str,
    body: dict[str, Any] | None,
) -> JSONResponse:
    config = load_host_management_config(settings.host_management_config, namespace)
    action = "frontend-profile.read" if method == "GET" else "frontend-profile.write"
    denied = authorize_management(config, token, headers, action)
    if denied is not None:
        return denied
    if config.frontend_profile is None:
        return _error(403, "PERMISSION_DENIED")
    if namespace is None or not settings.database_url.startswith(("postgres://", "postgresql://")):
        return _error(503, "MANAGEMENT_UNAVAILABLE")
    store = FrontendProfileManagementStore(settings.database_url, deployment_namespace=namespace)
    service = FrontendProfileService(
        PostgresClientCapabilityRegistry(settings.database_url, deployment_namespace=namespace)
    )

    def change() -> None:
        assert config.frontend_profile is not None and body is not None
        service.apply_approved(
            config.frontend_profile,
            host_app_id=config.trust.host_app_id,
            namespace_id=config.trust.namespace_id,
            active=body["active"],
        )

    try:
        result = (
            store.read(config.trust, config.frontend_profile)
            if body is None
            else store.apply(
                config.trust,
                config.frontend_profile,
                body["expectedRevision"],
                body["operationId"],
                body["active"],
                change,
            )
        )
    except (HostManagementConflict, FrontendProfileServiceError, ClientCapabilityError):
        return _error(409, "CONFLICT")
    except HostManagementExpired:
        return _error(403, "PERMISSION_DENIED")
    except HostManagementUnavailable:
        return _error(503, "MANAGEMENT_UNAVAILABLE")
    return JSONResponse(content=result, headers={"Cache-Control": "no-store"})


def register_frontend_profile_management(
    app: FastAPI, settings: ZebraAgentSettings, namespace: str | None
) -> None:
    register_management_endpoint(app, PATH, partial(_perform, settings, namespace), timeout=5.0)
