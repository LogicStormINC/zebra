"""Frozen neutral Effect inputs and descriptor provenance at the Worker boundary."""

import json
from datetime import UTC, datetime

import pytest
from agent_core.domain.coverage_contracts import CoverageRefusalReason, CoverageRefusedError
from agent_core.domain.tools import ToolCall, ToolCallStatus, ToolResult
from agent_integrations.host_tools.contracts import HostToolManifest
from zebra_agent_worker.coverage_effect_validation import (
    CREATE,
    create_arguments,
    create_call_id,
    frozen_manifest,
    validate_result,
)

from tests.worker.test_coverage_bootstrap import inputs


def test_neutral_create_uses_frozen_scope_and_scalar_source_resource():
    env = inputs(v2=True)
    arguments = create_arguments(env.admission)
    assert arguments == {
        "source_ref": "collection",
        "scope": env.admission.contract.scope.model_dump(mode="json"),
        "contract_digest": env.admission.contract.digest,
        "content_requirements": ["canonical_body"],
    }
    assert (
        frozen_manifest(env.source.host.manifest, env.admission.contract)
        == env.source.host.manifest
    )
    with pytest.raises(ValueError, match="unsupported"):
        frozen_manifest(env.source.host.manifest)


@pytest.mark.parametrize("change", ["scope", "resource", "argument", "risk", "idempotency"])
def test_neutral_manifest_cannot_weaken_frozen_create_requirements(change):
    env = inputs(v2=True)
    payload = env.source.host.manifest.to_payload()
    payload.pop("manifestDigest")
    tool = next(item for item in payload["tools"] if item["name"] == CREATE)
    if change == "scope":
        tool["scopes"] = [env.admission.contract.source_definition.create_scope]
    elif change == "resource":
        tool["resourceBindings"][0]["resourceType"] = "other.collection"
    elif change == "argument":
        tool["resourceBindings"][0]["argumentPointer"] = "/history_ref"
    elif change == "risk":
        tool["risk"] = "read"
    else:
        tool["idempotency"] = "none"
    with pytest.raises(ValueError, match="unsupported"):
        frozen_manifest(HostToolManifest.from_payload(payload), env.admission.contract)


@pytest.mark.parametrize(
    "change", [
        None, "dataset", "revision", "resource_type", "resource_id", "workspace", "authority",
        "scope", "contract", "legacy_wire",
    ],
)
def test_effect_result_checks_every_neutral_frozen_provenance_field(change):
    env = inputs(v2=True)
    arguments = create_arguments(env.admission)
    call = ToolCall(
        tool_call_id=create_call_id(
            "key", env.host, env.source.host.manifest, arguments, env.admission.source_resource,
        ),
        name=CREATE, arguments=arguments, created_at=datetime.now(UTC),
    )
    response = env.wire.request(
        "POST", env.host.origin, headers={"X-Zebra-Host-Auth": "fixture"},
        body={"toolName": CREATE, "arguments": arguments},
        timeout_seconds=30,
    )
    value = json.loads(response.body["output"])
    provenance = value["provenance"]
    if change in {"dataset", "revision", "workspace", "authority"}:
        key = {"revision": "dataset_revision", "workspace": "workspace_ref",
               "authority": "authority_revision"}.get(change, change)
        provenance[key] = "f" * 64 if change == "authority" else "foreign"
    elif change in {"resource_type", "resource_id"}:
        provenance["resource_ref"]["type" if change == "resource_type" else "id"] = "foreign"
    elif change == "scope":
        value["scope"]["selection_ref"] = "foreign"
    elif change == "contract":
        value["snapshot"]["contract_digest"] = "f" * 64
    elif change == "legacy_wire":
        value.pop("schema_version")
    result = ToolResult(
        tool_call_id=call.tool_call_id, status=ToolCallStatus.EXECUTED, output=json.dumps(value),
    )
    if change is None:
        assert validate_result(
            result, call, env.admission, env.host, env.source.host.manifest,
        ) == result
    else:
        with pytest.raises(CoverageRefusedError) as refused:
            validate_result(result, call, env.admission, env.host, env.source.host.manifest)
        assert refused.value.reason is (
            CoverageRefusalReason.UPSTREAM_NOT_READY if change == "legacy_wire"
            else CoverageRefusalReason.AUTHORITY_INVALID
        )
