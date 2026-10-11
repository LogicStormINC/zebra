"""Frozen snapshot-create inputs; no dispatch or persistence mutations."""

import json
from dataclasses import fields
from datetime import UTC, datetime
from uuid import NAMESPACE_URL, uuid5

from agent_core.domain.coverage_contracts import CoverageRefusalReason as Reason
from agent_core.domain.coverage_contracts import CoverageRefusedError, coverage_digest
from agent_core.domain.coverage_task_admission import CoverageTaskAdmission
from agent_core.domain.host_authority import HostContextEnvelope, HostResourceRef
from agent_core.domain.host_capability_manifests import ResourceBindingRule
from agent_core.domain.identifiers import ToolCallId
from agent_core.domain.tools import (
    ToolCall,
    ToolCallStatus,
    ToolExecutionLocation,
    ToolIdempotency,
    ToolResult,
    ToolRisk,
)
from agent_core.ports.effect_dispatch import effect_input
from agent_integrations.coverage_snapshot_invocation import HISTORY_RESOURCE_TYPE, unique_object
from agent_integrations.coverage_snapshot_source import MAX_RECORDS
from agent_integrations.coverage_snapshot_wire import SnapshotWire, parse
from agent_integrations.host_tools.contracts import HostToolManifest

CREATE = "dataset.snapshot.create"


def frozen_manifest(value: HostToolManifest) -> HostToolManifest:
    if type(value) is not HostToolManifest or value.digest == "0" * 64:
        raise ValueError("coverage requires a real Host manifest")
    for entry in value.tools:
        if entry.__dict__.keys() != {field.name for field in fields(entry)}:
            raise ValueError("Host tool carries unknown fields")
        if type(entry.timeout_seconds) is not int or type(entry.max_output_bytes) is not int:
            raise ValueError("Host tool bounds must be integers")
        if type(entry.parallel_safe) is not bool:
            raise ValueError("Host tool parallel marker must be boolean")
        if (
            type(entry.risk) is not ToolRisk
            or type(entry.execution_location) is not ToolExecutionLocation
            or type(entry.idempotency) is not ToolIdempotency
        ):
            raise ValueError("Host tool raw enums must match the frozen contract")
    for _, rules in value.tool_resource_bindings:
        for rule in rules:
            ResourceBindingRule.model_validate(effect_input(rule), strict=True, extra="forbid")
    pinned = HostToolManifest.from_payload(value.to_payload())
    if pinned != value:
        raise ValueError("Host manifest raw shape differs from its frozen contract")
    tool = pinned.get(CREATE)
    rules = pinned.resource_bindings_for(CREATE)
    if (
        tool is None
        or tool.risk is not ToolRisk.WRITE
        or tool.execution_location is not ToolExecutionLocation.HOST
        or tool.idempotency is not ToolIdempotency.REQUIRED
        or "history.snapshot.write" not in tool.scopes
        or not pinned.resource_bindings_declared
        or len(rules) != 1
        or rules[0].argument_pointer != "/history_ref"
        or rules[0].resource_type != HISTORY_RESOURCE_TYPE
        or not rules[0].required
    ):
        raise ValueError("Host snapshot-create write/resource contract is unsupported")
    return pinned


def create_arguments(admission: CoverageTaskAdmission) -> dict[str, object]:
    return {
        "history_ref": admission.history_ref,
        "scope": admission.contract.scope.model_dump(mode="json"),
        "contract_digest": admission.contract.digest,
        "content_requirements": list(admission.contract.content_requirements),
    }


def create_call_id(
    key: str,
    context: HostContextEnvelope,
    manifest: HostToolManifest,
    arguments: dict[str, object],
    resource: HostResourceRef,
) -> ToolCallId:
    # ponytail: pin CoverageInvocation's existing identity, never mint a retry key.
    digest = coverage_digest(
        {
            "key": key,
            "binding": context.model_dump(mode="json"),
            "context": context.model_dump(mode="json"),
            "manifest": manifest.digest,
            "tool": CREATE,
            "arguments": arguments,
            "resource": resource.model_dump(mode="json"),
        }
    )
    return ToolCallId(uuid5(NAMESPACE_URL, "zebra-coverage-create/1:" + digest))


def validate_result(
    result: ToolResult,
    call: ToolCall,
    admission: CoverageTaskAdmission,
    context: HostContextEnvelope,
    manifest: HostToolManifest,
) -> ToolResult:
    result = ToolResult.model_validate(effect_input(result), strict=True, extra="forbid")
    tool = manifest.get(CREATE)
    assert tool is not None
    if (
        result.tool_call_id != call.tool_call_id
        or result.status is not ToolCallStatus.EXECUTED
        or len(result.output.encode())
        > min(tool.max_output_bytes, 131072, context.limits.max_artifact_bytes)
    ):
        raise CoverageRefusedError(Reason.UPSTREAM_NOT_READY)
    try:
        value = json.loads(
            result.output,
            object_pairs_hook=unique_object,
            parse_constant=lambda _: (_ for _ in ()).throw(ValueError("NaN")),
        )
    except (ValueError, TypeError) as exc:
        raise CoverageRefusedError(Reason.UPSTREAM_NOT_READY) from exc
    wire = parse(SnapshotWire, value, Reason.UPSTREAM_NOT_READY)
    snapshot = wire.snapshot
    if (
        snapshot.namespace != context.namespace_id
        or snapshot.host_id != context.host_app_id
        or wire.provenance.history_ref != admission.history_ref
        or wire.provenance.workspace_ref != context.workspace_ref
        or wire.provenance.periods_digest != snapshot.authority_revision
        or wire.content_capabilities != ("canonical_body",)
        or wire.scope != admission.contract.scope
        or wire.scope.digest != snapshot.scope_digest
        or snapshot.contract_digest != admission.contract.digest
        or not snapshot.as_of <= wire.sealed_at < snapshot.expires_at
        or not snapshot.as_of <= datetime.now(UTC) < snapshot.expires_at
        or snapshot.record_count > MAX_RECORDS
    ):
        raise CoverageRefusedError(Reason.AUTHORITY_INVALID)
    return result
