"""Static native producer contract, assembled from the original native schemas."""

from typing import Any

from agent_core.domain.runtime_assembly import TEXT_OUTPUT_SCHEMA, TEXT_OUTPUT_SCHEMA_DIGEST
from agent_core.domain.runtime_bundle import (
    MAX_BUNDLE_BYTES,
    RuntimeDomains,
    runtime_bundle_catalog,
    runtime_bundle_catalog_digest,
    runtime_bundle_json_schema,
)
from agent_core.domain.runtime_bundle_json import json_digest

CONTRACT = "bundle-validation/1"
CONTRACT_PATH = "/management/v1/bundle-contract"
VALIDATION_PATH = "/management/v1/bundle-validation"


def native_bundle_contract() -> dict[str, Any]:
    """No operator approvals, private configuration or transport metadata included."""
    value: dict[str, Any] = {
        "contractVersion": CONTRACT,
        "envelopeSchema": runtime_bundle_json_schema(),
        "componentCatalog": runtime_bundle_catalog(),
        "catalogDigest": runtime_bundle_catalog_digest(),
        "nativeFormats": {
            "definition": ["agent-definition/1", "agent-definition/2"],
            "definitionSnapshot": ["agent-definition-snapshot/1", "agent-definition-snapshot/2"],
        },
        "execution": {
            "mode": "chat",
            "thinking": "auto",
            "output": "text",
            "outputSchema": dict(TEXT_OUTPUT_SCHEMA),
            "outputSchemaDigest": TEXT_OUTPUT_SCHEMA_DIGEST,
            "configurableDomains": ["model", "instructions"],
            "pinnedDomains": [
                name
                for name in RuntimeDomains.model_fields
                if name not in {"model", "instructions"}
            ],
            "nativeScriptAbi": "unsupported",
        },
        "transport": {"maxBundleBytes": MAX_BUNDLE_BYTES},
        "capabilities": {
            "contractRead": "supported",
            "validation": "supported",
            "publication": "unsupported",
            "persistence": "unsupported",
            "execution": "unsupported",
        },
    }
    return {**value, "contractDigest": json_digest(value)}


def bundle_contract_digest() -> str:
    return str(native_bundle_contract()["contractDigest"])
