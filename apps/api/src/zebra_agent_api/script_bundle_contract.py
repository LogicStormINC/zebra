"""Producer-owned pure ScriptBundle validation; old Bundle1 contract is unchanged."""

from typing import Any

from agent_core.domain.runtime_bundle import MAX_BUNDLE_BYTES
from agent_core.domain.runtime_bundle_json import json_digest
from agent_core.domain.script_bundle import ScriptBundle

CONTRACT = "script-bundle-validation/1"
CONTRACT_PATH = "/management/v1/script-bundle-contract"
VALIDATION_PATH = "/management/v1/script-bundle-validation"
HEADER = "x-runtime-script-bundle-contract"


def native_script_bundle_contract() -> dict[str, Any]:
    value: dict[str, Any] = {
        "contractVersion": CONTRACT,
        "requestSchema": ScriptBundle.model_json_schema(),
        "paths": {"contract": CONTRACT_PATH, "validation": VALIDATION_PATH},
        "requiredHeader": HEADER,
        "actions": ["script-bundle.contract.read", "script-bundle.validate"],
        "credential": "rtbv_",
        "approval": "cloud-agent.bundle-management-approval/1",
        "abi": "cloud-agent.native-script/1",
        "nativeFormats": {
            "bundle": "cloud-agent.script-bundle/1",
            "assembly": "cloud-agent.script-assembly/1",
            "catalog": "cloud-agent.execution-catalog/2",
        },
        "resultFields": [
            "inputDigest",
            "scriptBundleDigest",
            "baseBundleDigest",
            "assemblyDigest",
            "approvalDigest",
            "checks",
            "capabilities",
        ],
        "checks": {
            "scriptBundle": "passed",
            "assetApproval": "passed",
            "worker": "not_checked",
            "publication": "not_performed",
        },
        "transport": {
            "maxRequestBytes": MAX_BUNDLE_BYTES,
            "slotsPerInstance": 8,
            "bodyTimeoutMilliseconds": 200,
            "responseTimeoutSeconds": 1,
        },
        "capabilities": {
            "validation": "supported",
            "assetApproval": "observed",
            "sourceExecution": "not_performed",
            "worker": "not_checked",
            "publication": "not_performed",
            "persistence": "not_performed",
            "evalAuthority": False,
            "coverageAuthority": False,
        },
    }
    return value | {"contractDigest": json_digest(value)}
