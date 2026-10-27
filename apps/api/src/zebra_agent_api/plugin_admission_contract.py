"""Versioned producer contract: scoped package checks are not execution authority."""

from typing import Annotated, Any, Literal
from uuid import UUID

from agent_core.domain.runtime_bundle_json import json_digest
from agent_core.domain.runtime_bundle_types import BundleScope, BundleValue, Digest
from pydantic import Field

PATH = "/management/v1/plugin-admission"
CONTRACT_PATH = PATH + "/contract"
HEADER = "x-runtime-plugin-contract"
CONTRACT = "plugin-admission/1"
MAX_BYTES = 1_500_000


class FileInput(BundleValue):
    path: Annotated[str, Field(min_length=1, max_length=512)]
    content_base64: Annotated[str, Field(max_length=87384)]


class ValidatePackage(BundleValue):
    action: Literal["validate"]
    scope: BundleScope
    files: Annotated[list[FileInput], Field(min_length=2, max_length=64)]


class PublishPackage(BundleValue):
    action: Literal["publish"]
    scope: BundleScope
    operation_id: Annotated[str, Field(pattern=r"^[0-9a-f-]{36}$")]
    package_digest: Digest

    def operation(self) -> str:
        if str(UUID(self.operation_id)) != self.operation_id:
            raise ValueError("INVALID_OPERATION")
        return self.operation_id


def plugin_admission_contract() -> dict[str, Any]:
    value: dict[str, Any] = {
        "contractVersion": CONTRACT,
        "path": PATH,
        "contractPath": CONTRACT_PATH,
        "header": HEADER,
        "credential": "rtpa_",
        "approval": "cloud-agent.plugin-admission-approval/1",
        "scope": list(BundleScope.model_fields),
        "validate": {
            "fields": ["action", "scope", "files"],
            "fileFields": ["path", "content_base64"],
            "manifest": "plugin.json/0.2",
            "result": ["packageDigest", "manifestDigest", "manifest"],
        },
        "publish": {
            "fields": ["action", "scope", "operation_id", "package_digest"],
            "gate": "current shared publisher approval AND exact approved mounted package",
            "result": "immutable PluginPackagePin; no installation or execution grant",
        },
        "get": {
            "operationHeader": "x-runtime-operation",
            "currentHeader": "x-runtime-plugin-digest",
            "exclusiveSelectors": True,
            "receipt": "immutable original result plus separate currentApproval",
            "missing": "not proof of non-commit",
            "unknown": "GET only; never automatic POST",
        },
        "limits": {
            "bodyBytes": MAX_BYTES,
            "files": 64,
            "fileBytes": 65536,
            "expandedBytes": 1048576,
            "manifestBytes": 16384,
            "slots": 8,
            "bodyMillis": 500,
            "responseSeconds": 6,
        },
        "capabilities": {
            "execute": False,
            "install": False,
            "workerRevocation": False,
            "coverageAuthority": False,
            "automaticRetry": False,
        },
    }
    return value | {"contractDigest": json_digest(value)}
