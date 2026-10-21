"""Scoped pure package checks; neither execution approval nor durable build evidence."""

from datetime import UTC, datetime
from functools import partial
from hashlib import sha256
from typing import Any

from agent_core.domain.runtime_bundle_json import load_bundle_json
from fastapi import FastAPI
from fastapi.responses import JSONResponse
from zebra_agent_config import ZebraAgentSettings

from zebra_agent_api.bundle_management import _authorize
from zebra_agent_api.runtime_management import _error
from zebra_agent_api.script_validation_config import load_script_validation_approval
from zebra_agent_api.script_validation_contract import (
    CONTRACT,
    CONTRACT_PATH,
    MAX_REQUEST_BYTES,
    VALIDATION_PATH,
    ScriptValidationRequest,
    native_script_validation_contract,
)
from zebra_agent_api.validation_transport import register_validation_routes

BODY_TIMEOUT = 0.2
REQUEST_TIMEOUT = 1.0


def _perform(
    settings: ZebraAgentSettings,
    namespace: str | None,
    token: str,
    headers: dict[str, list[str]],
    action: str,
    contract_header: str | None,
    raw: bytes,
) -> JSONResponse:
    initial = load_script_validation_approval(settings.script_validation_config, namespace)
    denied = _authorize(initial, token, headers, action)
    if denied is not None:
        return denied
    contract = native_script_validation_contract()
    result: dict[str, Any] = {
        "contractVersion": CONTRACT,
        "contractDigest": contract["contractDigest"],
        "scope": initial.scope.model_dump(mode="json"),
        "trustRevision": initial.trust_revision,
    }
    if action == "script.contract.read":
        result["contract"] = contract
    else:
        if contract_header != contract["contractDigest"]:
            return _error(409, "CONTRACT_MISMATCH")
        try:
            request = ScriptValidationRequest.model_validate(load_bundle_json(raw))
            if request.scope != initial.scope:
                return _error(403, "SCOPE_MISMATCH")
            script = request.script()
        except (ValueError, TypeError, OverflowError, RecursionError):
            return _error(422, "SCRIPT_REJECTED")
        result.update(
            inputDigest="sha256:" + sha256(raw).hexdigest(),
            manifestDigest=script.manifest.digest,
            sourceDigest=script.manifest.source_digest,
            name=script.manifest.name,
            version=script.manifest.version,
            kind=script.manifest.kind,
            sourceBytes=len(script.source),
            checks={name: "passed" for name in contract["checks"]},
            capabilities=contract["capabilities"],
        )
    current = load_script_validation_approval(settings.script_validation_config, namespace)
    denied = _authorize(current, token, headers, action)
    if denied is not None:
        return denied
    if current != initial:
        return _error(403, "PERMISSION_DENIED")
    result["observedAt"] = datetime.now(UTC).isoformat()
    return JSONResponse(content=result, headers={"Cache-Control": "no-store"})


def register_script_validation(
    app: FastAPI, settings: ZebraAgentSettings, namespace: str | None
) -> None:
    register_validation_routes(
        app,
        partial(_perform, settings, namespace),
        contract_path=CONTRACT_PATH,
        validation_path=VALIDATION_PATH,
        token_pattern=r"rtsv_[A-Za-z0-9_-]{43}",
        contract_header="x-runtime-script-contract",
        max_bytes=MAX_REQUEST_BYTES,
        actions=("script.contract.read", "script.validate"),
        body_timeout=BODY_TIMEOUT,
        request_timeout=REQUEST_TIMEOUT,
    )
