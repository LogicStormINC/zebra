"""Producer-owned wire translation; ABI semantics remain in the existing domain."""

import base64
from typing import Annotated, Any, Literal

from agent_core.domain.native_script import MAX_SCRIPT_BYTES, NativeScript, parse_native_script
from agent_core.domain.runtime_bundle_json import json_digest
from agent_core.domain.runtime_bundle_types import BundleScope, BundleValue
from pydantic import Field

CONTRACT = "script-validation/1"
CONTRACT_PATH = "/management/v1/script-contract"
VALIDATION_PATH = "/management/v1/script-validation"
MAX_REQUEST_BYTES = 65_536
EncodedBytes = Annotated[
    str,
    Field(min_length=4, max_length=21_848, json_schema_extra={"contentEncoding": "base64"}),
]


class ScriptValidationRequest(BundleValue):
    schema_version: Literal["cloud-agent.script-validation-request/1"]
    scope: BundleScope
    manifest_base64: EncodedBytes
    source_base64: EncodedBytes

    def script(self) -> NativeScript:
        def decode(value: str) -> bytes:
            raw = base64.b64decode(value, validate=True)
            if (
                not 0 < len(raw) <= MAX_SCRIPT_BYTES
                or base64.b64encode(raw).decode("ascii") != value
            ):
                raise ValueError("CANONICAL_BASE64_REQUIRED")
            return raw

        return parse_native_script(decode(self.manifest_base64), decode(self.source_base64))


def native_script_validation_contract() -> dict[str, Any]:
    value: dict[str, Any] = {
        "contractVersion": CONTRACT,
        "requestSchema": ScriptValidationRequest.model_json_schema(),
        "abi": "cloud-agent.native-script/1",
        "checks": ["manifest", "sourceDigest", "sourceSyntax"],
        "transport": {
            "maxRequestBytes": MAX_REQUEST_BYTES,
            "maxManifestBytes": MAX_SCRIPT_BYTES,
            "maxSourceBytes": MAX_SCRIPT_BYTES,
            "byteEncoding": "canonical-base64",
            "slotsPerInstance": 8,
            "bodyTimeoutSeconds": "0.2",
            "responseTimeoutSeconds": 1,
        },
        "capabilities": {
            "validation": "supported",
            "sourceExecution": "not_performed",
            "assetApproval": "not_performed",
            "worker": "not_checked",
            "publication": "not_performed",
            "persistence": "not_performed",
            "coverageAuthority": False,
        },
    }
    return {**value, "contractDigest": json_digest(value)}
