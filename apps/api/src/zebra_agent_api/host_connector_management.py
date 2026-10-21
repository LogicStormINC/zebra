"""Approved outbound connector profile/binding management, independent of execution."""

from __future__ import annotations

from functools import partial
from typing import Any

from agent_core.domain.host_connectors import HostConnectorBinding
from agent_storage.postgres.host_connector_management import HostConnectorManagementStore
from agent_storage.postgres.host_management import (
    HostManagementConflict,
    HostManagementExpired,
    HostManagementUnavailable,
)
from fastapi import FastAPI
from fastapi.responses import JSONResponse
from zebra_agent_config import ZebraAgentSettings

from zebra_agent_api.host_connector_config import profile_wire
from zebra_agent_api.host_registry_config import load_host_management_config
from zebra_agent_api.management_transport import authorize_management, register_management_endpoint
from zebra_agent_api.runtime_management import _error

CONTRACT = "host-connector-management/1"
PATH = "/management/v1/host-connector"
REQUEST_TIMEOUT = 5.0


def binding_wire(binding: HostConnectorBinding | None) -> dict[str, Any] | None:
    if binding is None:
        return None
    return {
        "hostAppId": binding.host_app_id,
        "namespaceId": binding.namespace_id,
        "connectorId": binding.connector_id,
        "profileRevision": binding.profile_revision,
        "bindingRevision": binding.binding_revision,
        "active": binding.active,
    }


def _perform(
    settings: ZebraAgentSettings,
    namespace: str | None,
    token: str,
    headers: dict[str, list[str]],
    method: str,
    body: dict[str, Any] | None,
) -> JSONResponse:
    config = load_host_management_config(settings.host_management_config, namespace)
    denied = authorize_management(
        config, token, headers, "connector.read" if method == "GET" else "connector.write"
    )
    if denied is not None:
        return denied
    if config.connector_profile is None:
        return _error(403, "PERMISSION_DENIED")
    if namespace is None or not settings.database_url.startswith(("postgres://", "postgresql://")):
        return _error(503, "MANAGEMENT_UNAVAILABLE")
    store = HostConnectorManagementStore(settings.database_url, deployment_namespace=namespace)
    try:
        if body is None:
            result = store.read(config.trust, config.connector_profile)
        else:
            result = store.apply(
                config.trust,
                config.connector_profile,
                body["expectedRevision"],
                body["operationId"],
                body["active"],
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
            "binding": binding_wire(result.binding),
            "profile": profile_wire(result.profile),
            "approvedProfile": profile_wire(result.approved_profile),
            "revision": result.revision,
            "replayed": result.replayed,
        },
        headers={"Cache-Control": "no-store"},
    )


def register_host_connector_management(
    app: FastAPI, settings: ZebraAgentSettings, namespace: str | None
) -> None:
    register_management_endpoint(
        app, PATH, partial(_perform, settings, namespace), timeout=REQUEST_TIMEOUT
    )
