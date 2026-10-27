"""Product distributions reuse publisher approval, fixed receipts and bounded transport."""

from functools import partial
from hashlib import sha256
from typing import Any
from uuid import UUID

import psycopg
from agent_core.domain.plugin_distribution import PluginDistributionCommand
from agent_core.domain.runtime_bundle_json import json_digest, load_bundle_json
from agent_storage.postgres.host_management import HostManagementConflict, HostManagementUnavailable
from agent_storage.postgres.plugin_distribution import PluginDistributionStore
from agent_storage.postgres.plugin_publication_receipts import PluginAdmissionStore
from fastapi import FastAPI
from fastapi.responses import JSONResponse
from zebra_agent_config import ZebraAgentSettings

from zebra_agent_api.bundle_management import _authorize
from zebra_agent_api.plugin_admission_config import load_plugin_approval
from zebra_agent_api.runtime_management import _error
from zebra_agent_api.validation_transport import register_validation_routes

PATH = "/management/v1/plugin-distribution"
HEADER = "x-runtime-plugin-distribution-contract"


def plugin_distribution_contract() -> dict[str, Any]:
    value = {
        "contractVersion": "plugin-distribution/1",
        "path": PATH,
        "header": HEADER,
        "credential": "rtpa_",
        "approval": "cloud-agent.plugin-admission-approval/1",
        "writeAction": "plugin.publish",
        "readAction": "plugin.read",
        "fields": [
            "action",
            "scope",
            "recipient",
            "package_digest",
            "publication_operation",
            "operation_id",
            "expected_revision",
        ],
        "recipient": ["authority_issuer", "namespace_id", "principal_id", "workspace_id"],
        "get": "original operation header only; originalResult and separate currentDistribution",
        "publication": "exact current product publisher original plugin-admission/1 pin",
        "revocation": "install/enable/Turn/Worker current checks; no undo of committed effects",
        "legacy": "unmanaged unchanged; registered digest never falls back",
        "generation": "regrant never revives prior installation generation",
        "automaticRetry": False,
        "bodyBytes": 8192,
        "slots": 8,
    }
    return value | {"contractDigest": json_digest(value)}


def _perform(
    settings: ZebraAgentSettings,
    namespace: str | None,
    token: str,
    headers: dict[str, list[str]],
    action: str,
    header: str | None,
    raw: bytes,
) -> JSONResponse:
    try:
        approval = load_plugin_approval(settings.plugin_admission_config, namespace)
        is_get = action == "plugin.read"
        denied = _authorize(approval, token, headers, action)
        if denied is not None:
            return denied
        contract = plugin_distribution_contract()
        if header != contract["contractDigest"]:
            return _error(409, "CONTRACT_MISMATCH")
        assert namespace is not None
        receipts = PluginAdmissionStore(settings.database_url, namespace)
        store = PluginDistributionStore(settings.database_url, namespace)
        receipts.read(approval.trust)

        def recheck() -> None:
            if load_plugin_approval(settings.plugin_admission_config, namespace) != approval:
                raise PermissionError("PERMISSION_DENIED")

        result: dict[str, Any]
        if is_get:
            selectors = headers["x-runtime-operation"]
            if not selectors:
                result = {"contract": contract}
            else:
                op = selectors[0]
                if str(UUID(op)) != op:
                    raise ValueError("INVALID_OPERATION")
                original = receipts.read(approval.trust, op)
                if (
                    original is None
                    or original.get("contractVersion") != "plugin-distribution/1"
                    or original.get("scope") != approval.scope.model_dump(mode="json")
                ):
                    return _error(404, "NOT_FOUND")
                result = {
                    "originalResult": original,
                    "currentDistribution": store.current(approval.trust, original),
                }
        else:
            if headers["x-runtime-operation"]:
                raise ValueError("SELECTOR_ON_POST")
            command = PluginDistributionCommand.model_validate(
                load_bundle_json(raw, max_bytes=8192)
            )
            if command.scope != approval.scope:
                return _error(403, "SCOPE_MISMATCH")
            if (
                command.action == "distribute"
                and command.package_digest not in approval.package_digests
            ):
                return _error(403, "PACKAGE_NOT_APPROVED")
            original = store.apply(
                approval.trust, command, "sha256:" + sha256(raw).hexdigest(), recheck
            )
            result = {
                "originalResult": original,
                "currentDistribution": store.current(approval.trust, original),
            }
        recheck()
        receipts.read(approval.trust)
        return JSONResponse(
            {
                "contractVersion": "plugin-distribution/1",
                "contractDigest": contract["contractDigest"],
                "scope": approval.scope.model_dump(mode="json"),
                "trustRevision": approval.trust_revision,
                **result,
            },
            headers={"Cache-Control": "no-store"},
        )
    except HostManagementConflict:
        return _error(409, "OPERATION_CONFLICT")
    except (HostManagementUnavailable, PermissionError):
        return _error(403, "PERMISSION_DENIED")
    except (ValueError, TypeError, KeyError, OverflowError, RecursionError):
        return _error(422, "DISTRIBUTION_REJECTED")
    except (OSError, psycopg.Error, RuntimeError):
        return _error(503, "MANAGEMENT_UNAVAILABLE")


def register_plugin_distribution(
    app: FastAPI, settings: ZebraAgentSettings, namespace: str | None
) -> None:
    register_validation_routes(
        app,
        partial(_perform, settings, namespace),
        contract_path=PATH + "/contract",
        validation_path=PATH,
        token_pattern=r"rtpa_[A-Za-z0-9_-]{43}",
        contract_header=HEADER,
        max_bytes=8192,
        actions=("plugin.read", "plugin.publish"),
        body_timeout=0.5,
        request_timeout=6,
        read_validation_path=True,
        extra_headers=("x-runtime-operation",),
    )
