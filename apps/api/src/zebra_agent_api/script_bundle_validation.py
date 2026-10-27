"""Effect-free scoped script closure checks against the current private catalog."""

from datetime import UTC, datetime
from functools import partial
from hashlib import sha256
from typing import Any

from agent_core.domain.runtime_bundle import MAX_BUNDLE_BYTES
from agent_core.domain.runtime_bundle_json import json_digest, load_bundle_json
from agent_core.domain.script_bundle import ScriptBundle
from fastapi import FastAPI
from fastapi.responses import JSONResponse
from zebra_agent_config import ZebraAgentSettings
from zebra_agent_config.bundle_settings import load_execution_catalog
from zebra_agent_config.native_script import ScriptExecutionCatalog

from zebra_agent_api.bundle_management import _authorize
from zebra_agent_api.bundle_management_config import load_bundle_management_approval
from zebra_agent_api.runtime_management import _error
from zebra_agent_api.script_bundle_contract import (
    CONTRACT,
    CONTRACT_PATH,
    HEADER,
    VALIDATION_PATH,
    native_script_bundle_contract,
)
from zebra_agent_api.validation_transport import register_validation_routes


def _perform(
    settings: ZebraAgentSettings,
    namespace: str | None,
    token: str,
    headers: dict[str, list[str]],
    action: str,
    contract_header: str | None,
    raw: bytes,
) -> JSONResponse:
    initial = load_bundle_management_approval(settings.bundle_management_config, namespace)
    denied = _authorize(initial, token, headers, action)
    if denied is not None:
        return denied
    contract = native_script_bundle_contract()
    result: dict[str, Any] = {
        "contractVersion": CONTRACT,
        "contractDigest": contract["contractDigest"],
        "scope": initial.scope.model_dump(mode="json"),
        "trustRevision": initial.trust_revision,
    }
    if action == "script-bundle.contract.read":
        result["contract"] = contract
    else:
        if contract_header != contract["contractDigest"]:
            return _error(409, "CONTRACT_MISMATCH")
        try:
            bundle = ScriptBundle.model_validate(load_bundle_json(raw))
        except (ValueError, TypeError, OverflowError, RecursionError):
            return _error(422, "SCRIPT_BUNDLE_REJECTED")
        if bundle.base_bundle.manifest.scope != initial.scope:
            return _error(403, "SCOPE_MISMATCH")
        catalog = load_execution_catalog(settings.runtime_bundle_config)
        if catalog.scope != initial.scope:
            return _error(403, "SCOPE_MISMATCH")
        if not isinstance(catalog, ScriptExecutionCatalog):
            return _error(422, "SCRIPT_BUNDLE_REJECTED")
        try:
            assembly = catalog.resolve_scripts(bundle)
        except (PermissionError, ValueError, TypeError, OverflowError, RecursionError):
            return _error(422, "SCRIPT_BUNDLE_REJECTED")
        result.update(
            inputDigest="sha256:" + sha256(raw).hexdigest(),
            scriptBundleDigest=bundle.bundle_digest,
            baseBundleDigest=bundle.base_bundle.bundle_digest,
            assemblyDigest=assembly.assembly_digest,
            approvalDigest=json_digest(catalog.model_dump(mode="json")),
            checks=contract["checks"],
            capabilities=contract["capabilities"],
        )
        if load_execution_catalog(settings.runtime_bundle_config) != catalog:
            return _error(403, "PERMISSION_DENIED")
    current = load_bundle_management_approval(settings.bundle_management_config, namespace)
    denied = _authorize(current, token, headers, action)
    if denied is not None:
        return denied
    if current != initial:
        return _error(403, "PERMISSION_DENIED")
    result["observedAt"] = datetime.now(UTC).isoformat()
    return JSONResponse(content=result, headers={"Cache-Control": "no-store"})


def register_script_bundle_validation(
    app: FastAPI, settings: ZebraAgentSettings, namespace: str | None
) -> None:
    register_validation_routes(
        app,
        partial(_perform, settings, namespace),
        contract_path=CONTRACT_PATH,
        validation_path=VALIDATION_PATH,
        token_pattern=r"rtbv_[A-Za-z0-9_-]{43}",
        contract_header=HEADER,
        max_bytes=MAX_BUNDLE_BYTES,
        actions=("script-bundle.contract.read", "script-bundle.validate"),
        body_timeout=0.2,
        request_timeout=1.0,
    )
