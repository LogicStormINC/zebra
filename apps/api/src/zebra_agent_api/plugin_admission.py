"""Bounded product package admission; immutable publishing does not install or run."""

import asyncio
import base64
from functools import partial
from hashlib import sha256
from pathlib import Path
from typing import Any
from uuid import UUID

import psycopg
from agent_core.domain.runtime_bundle_json import load_bundle_json
from agent_core.ports.artifact_object_store import ArtifactObjectStorePort
from agent_integrations.plugins.package_integrity import (
    PluginPackageFile,
    validate_plugin_package_files,
)
from agent_integrations.plugins.publication import PluginPackagePublicationService
from agent_storage import CloudCompositionSettings
from agent_storage.postgres.host_management import HostManagementConflict, HostManagementUnavailable
from agent_storage.postgres.plugin_publication_receipts import PluginAdmissionStore
from fastapi import FastAPI
from fastapi.responses import JSONResponse
from pydantic import TypeAdapter
from zebra_agent_config import ZebraAgentSettings

from zebra_agent_api.bundle_management import _authorize
from zebra_agent_api.plugin_admission_config import load_plugin_approval
from zebra_agent_api.plugin_admission_contract import (
    CONTRACT,
    CONTRACT_PATH,
    HEADER,
    MAX_BYTES,
    PATH,
    PublishPackage,
    ValidatePackage,
    plugin_admission_contract,
)
from zebra_agent_api.runtime_management import _error
from zebra_agent_api.validation_transport import register_validation_routes


def _perform(
    settings: ZebraAgentSettings,
    namespace: str | None,
    objects: ArtifactObjectStorePort | None,
    token: str,
    headers: dict[str, list[str]],
    action: str,
    contract_header: str | None,
    raw: bytes,
) -> JSONResponse:
    try:
        approval = load_plugin_approval(settings.plugin_admission_config, namespace)
    except (OSError, ValueError, TypeError, OverflowError, RecursionError):
        return _error(503, "MANAGEMENT_UNAVAILABLE")
    try:
        if namespace is None or not settings.database_url.startswith(
            ("postgres://", "postgresql://")
        ):
            return _error(503, "MANAGEMENT_UNAVAILABLE")
        selectors = headers["x-runtime-operation"], headers["x-runtime-plugin-digest"]
        is_get = action == "plugin.contract.read"
        if not is_get:
            if any(selectors):
                return _error(400, "INVALID_ARGUMENT")
            payload = load_bundle_json(raw, max_bytes=MAX_BYTES)
            action = (
                "plugin.publish"
                if isinstance(payload, dict) and payload.get("action") == "publish"
                else "plugin.validate"
            )
        elif any(selectors):
            if all(selectors):
                return _error(400, "INVALID_ARGUMENT")
            action = "plugin.read"
        denied = _authorize(approval, token, headers, action)
        if denied is not None:
            return denied
        contract = plugin_admission_contract()
        if action != "plugin.contract.read" and contract_header != contract["contractDigest"]:
            return _error(409, "CONTRACT_MISMATCH")
        store = PluginAdmissionStore(settings.database_url, namespace)

        def recheck() -> None:
            if load_plugin_approval(settings.plugin_admission_config, namespace) != approval:
                raise PermissionError("PERMISSION_DENIED")

        # Fresh shared approval, including contract reads; a stale replica's mounted
        # config cannot keep a revoked trust revision alive.
        original = store.read(approval.trust)
        result: dict[str, Any] = {
            "contractVersion": CONTRACT,
            "contractDigest": contract["contractDigest"],
            "scope": approval.scope.model_dump(mode="json"),
            "trustRevision": approval.trust_revision,
        }
        if action == "plugin.contract.read":
            result["contract"] = contract
        elif action == "plugin.read":
            operation, digest = selectors
            if operation:
                if str(UUID(operation[0])) != operation[0]:
                    raise ValueError("INVALID_OPERATION")
                original = store.read(approval.trust, operation[0])
                if (
                    original is None
                    or original.get("contractVersion") != CONTRACT
                    or original.get("scope") != result["scope"]
                ):
                    return _error(404, "NOT_FOUND")
                result["originalResult"] = original
                package_digest = original["packageDigest"]
            else:
                from agent_core.domain.runtime_bundle_types import Digest

                package_digest = TypeAdapter(Digest).validate_python(digest[0])
            result["currentApproval"] = {
                "packageDigest": package_digest,
                "approved": package_digest in approval.package_digests,
                "trustRevision": approval.trust_revision,
            }
        elif action == "plugin.validate":
            request = ValidatePackage.model_validate(load_bundle_json(raw, max_bytes=MAX_BYTES))
            if request.scope != approval.scope:
                return _error(403, "SCOPE_MISMATCH")
            files = []
            for item in request.files:
                content = base64.b64decode(item.content_base64, validate=True)
                if len(content) > (16384 if item.path == "plugin.json" else 65536):
                    raise ValueError("FILE_TOO_LARGE")
                files.append(
                    PluginPackageFile(item.path, len(content), sha256(content).hexdigest(), content)
                )
            if sum(file.size for file in files) > 1048576:
                raise ValueError("PACKAGE_TOO_LARGE")
            # No archive extraction, filesystem writes, import or subprocess execution.
            package = validate_plugin_package_files(tuple(files))
            if (
                load_bundle_json(package.canonical_manifest.encode()).get("manifest_version")
                != "0.2"
            ):
                raise ValueError("MANIFEST_VERSION")
            result.update(
                inputDigest="sha256:" + sha256(raw).hexdigest(),
                packageDigest=package.package_digest,
                manifestDigest=package.manifest_digest,
                manifest=package.manifest.model_dump(mode="json"),
            )
        else:
            publish = PublishPackage.model_validate(load_bundle_json(raw, max_bytes=MAX_BYTES))
            operation_id = publish.operation()
            if publish.scope != approval.scope:
                return _error(403, "SCOPE_MISMATCH")
            input_digest = "sha256:" + sha256(raw).hexdigest()
            original = store.read(approval.trust, operation_id)
            if original is not None:
                if (
                    original.get("inputDigest") != input_digest
                    or original.get("contractVersion") != CONTRACT
                ):
                    return _error(409, "OPERATION_CONFLICT")
                result["originalResult"] = original
            else:
                if publish.package_digest not in approval.package_digests:
                    return _error(403, "PACKAGE_NOT_APPROVED")
                if objects is None or not settings.plugins.bundle_root:
                    return _error(503, "MANAGEMENT_UNAVAILABLE")
                publisher = PluginPackagePublicationService(
                    Path(settings.plugins.bundle_root), approval.package_digests, objects, namespace
                )
                pin = asyncio.run(publisher.publish(package_digest=publish.package_digest))
                receipt = {
                    "contractVersion": CONTRACT,
                    "scope": result["scope"],
                    "operationId": operation_id,
                    "inputDigest": input_digest,
                    "packageDigest": pin.package_digest,
                    "pin": pin.model_dump(mode="json"),
                }
                result["originalResult"] = store.record(
                    approval.trust, operation_id, input_digest, receipt, recheck
                )
        recheck()
        store.read(approval.trust)
        return JSONResponse(result, headers={"Cache-Control": "no-store"})
    except HostManagementConflict:
        return _error(409, "OPERATION_CONFLICT")
    except (HostManagementUnavailable, PermissionError):
        return _error(403, "PERMISSION_DENIED")
    except (ValueError, TypeError, KeyError, OverflowError, RecursionError):
        return _error(422, "PACKAGE_REJECTED")
    except (OSError, psycopg.Error, RuntimeError):
        return _error(503, "MANAGEMENT_UNAVAILABLE")


def register_plugin_admission(
    app: FastAPI,
    settings: ZebraAgentSettings,
    namespace: str | None,
    cloud: CloudCompositionSettings | None = None,
) -> None:
    from zebra_agent_api.plugin_distribution import register_plugin_distribution

    register_plugin_distribution(app, settings, namespace)
    register_validation_routes(
        app,
        partial(
            _perform,
            settings,
            namespace,
            cloud.artifact_objects if cloud and settings.plugin_admission_config else None,
        ),
        contract_path=CONTRACT_PATH,
        validation_path=PATH,
        token_pattern=r"rtpa_[A-Za-z0-9_-]{43}",
        contract_header=HEADER,
        max_bytes=MAX_BYTES,
        actions=("plugin.contract.read", "plugin.validate"),
        body_timeout=0.5,
        request_timeout=6,
        read_validation_path=True,
        extra_headers=("x-runtime-operation", "x-runtime-plugin-digest"),
    )
