"""Explicit additive script publisher contract; base Bundle1 remains unchanged."""

from typing import Any

from agent_core.domain.runtime_bundle_json import json_digest

CONTRACT = "script-publication/1"
PATH = "/management/v1/script-publication"
HEADER = "x-runtime-publication-contract"


def script_publication_contract() -> dict[str, Any]:
    value: dict[str, Any] = {
        "contractVersion": CONTRACT,
        "path": PATH,
        "methods": ["GET", "POST"],
        "requiredHeader": HEADER,
        "credential": "rtpub_",
        "approval": "cloud-agent.publication-approval/1",
        "scope": [
            "authority_issuer",
            "namespace_id",
            "deployment_id",
            "target_id",
            "product_id",
            "environment",
        ],
        "materialize": {
            "fields": [
                "action",
                "operationId",
                "expectedRevision",
                "versionId",
                "version",
                "bundle",
            ],
            "bundle": "cloud-agent.script-bundle/1",
            "catalog": "cloud-agent.execution-catalog/2",
            "definition": "agent-definition/3",
            "assembly": "cloud-agent.script-assembly/1",
        },
        "publish": {
            "fields": ["action", "operationId", "expectedRevision", "versionId", "evidenceId"],
            "gate": "current trusted evaluator, policy, passed exact Definition digest",
        },
        "references": [
            "exact runtime-bundle/<base digest>@1",
            "exact script-bundle/<outer digest>@1",
        ],
        "receipt": {
            "selector": "X-Runtime-Operation",
            "sameOperationAcrossChannels": "conflict",
            "missing": "not proof of non-commit",
        },
        "resultFields": [
            "publicationContract",
            "scriptBundleDigest",
            "operationId",
            "revision",
            "inputDigest",
            "action",
            "definitionId",
            "versionId",
            "definitionDigest",
            "bundleDigest",
            "assemblyDigest",
        ],
        "publishResultFields": ["releaseId", "releaseRevision", "evidenceId"],
        "limits": {
            "bodyBytes": 262144,
            "sharedPublisherSlots": 4,
            "bodyMillis": 500,
            "responseSeconds": 6,
        },
        "capabilities": {
            "sourceUpload": False,
            "execute": False,
            "createEvalEvidence": False,
            "coverageAuthority": False,
            "automaticRetry": False,
        },
    }
    return value | {"contractDigest": json_digest(value)}
