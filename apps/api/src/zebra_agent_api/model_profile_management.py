"""Scoped registration and original-operation reads for immutable model profiles."""

from functools import partial
from typing import Annotated
from uuid import UUID

import psycopg
from agent_core.domain.runtime_assembly import (
    RuntimeProviderProfile,
    canonical_provider_profile_digest,
)
from agent_core.domain.runtime_bundle_json import json_digest, load_bundle_json
from agent_core.domain.runtime_bundle_types import ArtifactPin, BundleValue, Identifier
from agent_storage.postgres.database import PostgresDatabase
from agent_storage.postgres.model_profile_registration import (
    ModelProfileRegistrationConflict,
    PostgresModelProfileRegistrations,
)
from fastapi import FastAPI
from fastapi.responses import JSONResponse
from pydantic import Field
from zebra_agent_config import ZebraAgentSettings
from zebra_agent_config.bundle_settings import load_execution_catalog

from zebra_agent_api.bundle_management import _authorize
from zebra_agent_api.bundle_management_config import load_bundle_management_approval
from zebra_agent_api.runtime_management import _error
from zebra_agent_api.validation_transport import register_validation_routes

CONTRACT = "cloud-agent.model-profile-registration/1"
PATH = "/v1/management/model-profile-registrations/{operationId}"
READ = "model-profile.registration.read"
WRITE = "model-profile.register"


class RegistrationRequest(BundleValue):
    modelConfigId: Identifier
    revision: Annotated[int, Field(ge=1, le=2**53 - 1)]
    model: Identifier
    approvedProviderProfile: ArtifactPin
    displayName: Annotated[str, Field(min_length=1, max_length=256)] | None = None
    expectedConnectionDigest: Annotated[str, Field(pattern=r"^sha256:[0-9a-f]{64}$")] | None = None


def perform(
    settings: ZebraAgentSettings,
    namespace: str | None,
    token: str,
    headers: dict[str, list[str]],
    action: str,
    contract_header: str | None,
    raw: bytes,
) -> JSONResponse:
    approval = load_bundle_management_approval(settings.bundle_management_config, namespace)
    denied = _authorize(approval, token, headers, action)
    if denied is not None:
        return denied
    try:
        operation_id = UUID(headers["operationId"][0])
        if str(operation_id) != headers["operationId"][0]:
            raise ValueError("noncanonical UUID")
        request = (
            RegistrationRequest.model_validate(load_bundle_json(raw)) if action == WRITE else None
        )
    except (ValueError, TypeError, RecursionError):
        return _error(400, "INVALID_ARGUMENT")
    if request is not None and contract_header != CONTRACT:
        return _error(409, "CONTRACT_MISMATCH")
    store = PostgresModelProfileRegistrations(
        PostgresDatabase(settings.database_url, deployment_namespace=approval.scope.namespace_id)
    )
    try:
        if request is not None:
            request_digest = json_digest(request.model_dump(mode="json", exclude_none=True))
            existing = store.lookup_operation(approval.scope, operation_id)
            if existing is not None:
                if existing["request_digest"] != request_digest:
                    return _error(409, "CONFLICT")
            else:
                catalog = load_execution_catalog(settings.runtime_bundle_config)
                if catalog.scope != approval.scope:
                    return _error(403, "SCOPE_MISMATCH")
                approved = next(
                    (p for p in catalog.providers if p.pin == request.approvedProviderProfile), None
                )
                if approved is None or request.model not in approved.models:
                    return _error(403, "PERMISSION_DENIED")
                if (
                    request.expectedConnectionDigest is not None
                    and request.expectedConnectionDigest
                    != json_digest([approved.base_url, approved.api_key_env])
                ):
                    return _error(409, "CONNECTION_MISMATCH")
                profile_data = approved.model_dump(mode="json", exclude={"pin"})
                profile_data["models"] = [request.model]
                if request.displayName is not None:
                    profile_data["display_name"] = request.displayName
                identity = json_digest(
                    [approval.scope.model_dump(mode="json"), request.modelConfigId]
                ).removeprefix("sha256:")
                profile = RuntimeProviderProfile.model_validate(
                    {
                        **profile_data,
                        "pin": {
                            "kind": "provider-profile",
                            "id": "registered-" + identity,
                            "version": f"1.0.{request.revision}",
                            "digest": canonical_provider_profile_digest(profile_data),
                        },
                    }
                )
                if (
                    load_bundle_management_approval(settings.bundle_management_config, namespace)
                    != approval
                    or _authorize(approval, token, headers, action) is not None
                ):
                    return _error(403, "PERMISSION_DENIED")
                store.register(
                    approval.scope,
                    operation_id,
                    request.modelConfigId,
                    request.revision,
                    request_digest,
                    profile,
                )
        result = store.lookup_operation(approval.scope, operation_id)
    except ModelProfileRegistrationConflict:
        return _error(409, "CONFLICT")
    except psycopg.Error:
        return _error(503, "MANAGEMENT_UNAVAILABLE")
    if result is None:
        return _error(404, "NOT_FOUND")
    return JSONResponse(
        content={
            "contractVersion": CONTRACT,
            "operationId": str(operation_id),
            "modelConfigId": result["model_config_id"],
            "revision": result["revision"],
            "profilePin": result["profile"]["pin"],
            "model": result["profile"]["models"][0],
        },
        headers={"Cache-Control": "no-store"},
    )


def register_model_profile_management(
    app: FastAPI, settings: ZebraAgentSettings, namespace: str | None
) -> None:
    register_validation_routes(
        app,
        partial(perform, settings, namespace),
        contract_path="",
        validation_path=PATH,
        token_pattern=r"rtbv_[A-Za-z0-9_-]{43}",
        contract_header="x-runtime-model-profile-contract",
        max_bytes=4096,
        actions=(READ, WRITE),
        body_timeout=0.2,
        request_timeout=1.0,
        read_validation_path=True,
        write_method="PUT",
        operation_path_parameter="operationId",
    )
