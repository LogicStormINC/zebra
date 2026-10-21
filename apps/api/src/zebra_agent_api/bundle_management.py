"""Pure scoped Bundle validation; retained bounded threads, no execution effects."""

from __future__ import annotations

import hashlib
import hmac
from datetime import UTC, datetime
from functools import partial
from typing import TYPE_CHECKING, Any

from agent_core.domain.runtime_bundle import MAX_BUNDLE_BYTES, parse_runtime_bundle
from agent_core.domain.runtime_bundle_json import json_digest
from fastapi import FastAPI
from fastapi.responses import JSONResponse
from zebra_agent_config import ZebraAgentSettings
from zebra_agent_config.bundle_settings import load_execution_catalog

from zebra_agent_api.bundle_management_config import (
    BundleManagementApproval,
    load_bundle_management_approval,
)
from zebra_agent_api.bundle_management_contract import (
    CONTRACT,
    CONTRACT_PATH,
    VALIDATION_PATH,
    native_bundle_contract,
)
from zebra_agent_api.runtime_management import _HEADERS, _error
from zebra_agent_api.validation_transport import register_validation_routes

if TYPE_CHECKING:
    from zebra_agent_api.script_validation_config import ScriptValidationApproval

BODY_TIMEOUT = 0.2
REQUEST_TIMEOUT = 1.0


def _authorize(
    approval: BundleManagementApproval | ScriptValidationApproval,
    token: str,
    headers: dict[str, list[str]],
    action: str,
) -> JSONResponse | None:
    if not hmac.compare_digest(
        hashlib.sha256(token.encode()).hexdigest(), approval.credential_sha256
    ):
        return _error(401, "UNAUTHENTICATED")
    scope = approval.scope
    expected = {
        "deploymentId": scope.deployment_id,
        "audience": approval.audience,
        "productId": scope.product_id,
        "environment": scope.environment,
        "trustRevision": str(approval.trust_revision),
    }
    if any(headers[header] != [expected[field]] for field, header in _HEADERS.items()):
        return _error(403, "SCOPE_MISMATCH")
    if action not in approval.actions or approval.deadline <= datetime.now(UTC):
        return _error(403, "PERMISSION_DENIED")
    return None


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
    contract = native_bundle_contract()
    result: dict[str, Any] = {
        "contractVersion": CONTRACT,
        "contractDigest": contract["contractDigest"],
        "scope": initial.scope.model_dump(mode="json"),
        "trustRevision": initial.trust_revision,
    }
    if action == "bundle.contract.read":
        result["contract"] = contract
    else:
        if contract_header != contract["contractDigest"]:
            return _error(409, "CONTRACT_MISMATCH")
        try:
            bundle = parse_runtime_bundle(raw)
        except (ValueError, TypeError, OverflowError, RecursionError):
            return _error(422, "BUNDLE_REJECTED")
        if bundle.manifest.scope != initial.scope:
            return _error(403, "SCOPE_MISMATCH")
        catalog = load_execution_catalog(settings.runtime_bundle_config)
        if catalog.scope != initial.scope:
            return _error(403, "SCOPE_MISMATCH")
        try:
            assembly = catalog.resolve(bundle)
            result.update(
                bundleDigest=bundle.bundle_digest,
                assemblyDigest=assembly.assembly_digest,
                approvalDigest=json_digest(catalog.model_dump(mode="json")),
                checks={
                    "bundle": "passed",
                    "assetApproval": "passed",
                    "worker": "not_checked",
                    "publication": "not_performed",
                },
            )
        except (ValueError, TypeError, OverflowError, RecursionError):
            return _error(422, "BUNDLE_REJECTED")
    current = load_bundle_management_approval(settings.bundle_management_config, namespace)
    denied = _authorize(current, token, headers, action)
    if denied is not None:
        return denied
    if current != initial:
        return _error(403, "PERMISSION_DENIED")
    result["observedAt"] = datetime.now(UTC).isoformat()
    return JSONResponse(content=result, headers={"Cache-Control": "no-store"})


def register_bundle_management(
    app: FastAPI, settings: ZebraAgentSettings, namespace: str | None
) -> None:
    register_validation_routes(
        app,
        partial(_perform, settings, namespace),
        contract_path=CONTRACT_PATH,
        validation_path=VALIDATION_PATH,
        token_pattern=r"rtbv_[A-Za-z0-9_-]{43}",
        contract_header="x-runtime-bundle-contract",
        max_bytes=MAX_BUNDLE_BYTES,
        actions=("bundle.contract.read", "bundle.validate"),
        body_timeout=BODY_TIMEOUT,
        request_timeout=REQUEST_TIMEOUT,
    )
