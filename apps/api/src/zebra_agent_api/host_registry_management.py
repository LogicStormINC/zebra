"""Bounded scoped Host administration; execution/connector authority is unchanged."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import replace
from functools import partial
from typing import Any

from agent_storage import CloudCompositionSettings
from agent_storage.postgres.host_management import (
    HostManagementConflict,
    HostManagementExpired,
    HostManagementStore,
    HostManagementUnavailable,
)
from fastapi import FastAPI
from fastapi.responses import JSONResponse
from zebra_agent_config import ZebraAgentSettings

from zebra_agent_api.host_registry_config import load_host_management_config, registry_wire
from zebra_agent_api.management_transport import authorize_management, register_management_endpoint
from zebra_agent_api.runtime_management import _error, register_runtime_management

CONTRACT = "host-registry-management/1"
PATH = "/management/v1/host-registry"
REQUEST_TIMEOUT = 5.0


def _perform(
    settings: ZebraAgentSettings,
    namespace: str | None,
    token: str,
    headers: dict[str, list[str]],
    method: str,
    body: dict[str, Any] | None,
) -> JSONResponse:
    config = load_host_management_config(settings.host_management_config, namespace)
    action = "host-registry.read" if method == "GET" else "host-registry.write"
    denied = authorize_management(config, token, headers, action)
    if denied is not None:
        return denied
    if namespace is None or not settings.database_url.startswith(("postgres://", "postgresql://")):
        return _error(503, "MANAGEMENT_UNAVAILABLE")
    store = HostManagementStore(settings.database_url, deployment_namespace=namespace)
    try:
        if body is None:
            result = store.read(config.trust)
        else:
            record = replace(config.registry, active=body["active"])
            result = store.apply(
                config.trust, record, body["expectedRevision"], body["operationId"]
            )
    except HostManagementConflict:
        return _error(409, "CONFLICT")
    except HostManagementExpired:
        return _error(403, "PERMISSION_DENIED")
    except HostManagementUnavailable:
        return _error(503, "MANAGEMENT_UNAVAILABLE")
    return JSONResponse(
        content={
            "contractVersion": CONTRACT,
            "registry": registry_wire(result.record),
            "revision": result.revision,
            "replayed": result.replayed,
        },
        headers={"Cache-Control": "no-store"},
    )


def register_host_registry_management(
    app: FastAPI,
    settings: ZebraAgentSettings,
    namespace: str | None,
) -> None:
    register_management_endpoint(
        app, PATH, partial(_perform, settings, namespace), timeout=REQUEST_TIMEOUT
    )


def register_management_routes(
    app: FastAPI,
    settings: ZebraAgentSettings,
    namespace: Callable[[], str | None],
    cloud_composition: CloudCompositionSettings | None = None,
) -> None:
    """Keep optional management composition lazy when both routes are disabled."""
    enabled = (
        settings.runtime_management_config
        or settings.host_management_config
        or settings.bundle_management_config
        or settings.script_validation_config
    )
    current = namespace() if enabled else None
    register_runtime_management(app, settings, current)
    from zebra_agent_api.bundle_management import register_bundle_management

    register_bundle_management(app, settings, current)
    from zebra_agent_api.script_validation import register_script_validation

    register_script_validation(app, settings, current)
    host_settings = (
        replace(settings, database_url=cloud_composition.dsn)
        if cloud_composition is not None
        else settings
    )
    register_host_registry_management(app, host_settings, current)
    from zebra_agent_api.host_connector_management import register_host_connector_management

    register_host_connector_management(app, host_settings, current)

def deployment_namespace(api: object) -> str | None:
    stores = getattr(api, "stores", None)
    namespace = getattr(stores, "deployment_namespace", None)
    if isinstance(namespace, str) and namespace.strip():
        return namespace
    settings = getattr(api, "settings", None)
    return "local" if getattr(settings, "deployment", None) == "local" else None
