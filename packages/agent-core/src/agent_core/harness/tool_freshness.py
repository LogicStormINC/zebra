"""Track whether successful mutations have fresh read evidence."""

from collections.abc import Mapping
from datetime import datetime

from agent_core.domain.identifiers import new_message_id
from agent_core.domain.messages import MessageRole, SessionMessage
from agent_core.domain.tools import ToolCall, ToolCallStatus, ToolResult
from agent_core.domain.verification_evidence import (
    VerificationEvidence,
    VerificationResourceRef,
    VerificationStatus,
)
from agent_core.harness.attempt_result import action_fingerprint
from agent_core.ports.tool_gateway import ToolGatewayPort


def declared_read_only_tools(tool_gateway: ToolGatewayPort) -> frozenset[str]:
    raw = getattr(tool_gateway, "read_only_tools", ())
    return frozenset(name for name in raw if isinstance(name, str) and name.strip())


def declared_mutation_tools(tool_gateway: ToolGatewayPort) -> frozenset[str]:
    raw = getattr(tool_gateway, "mutation_tools", ())
    return frozenset(name for name in raw if isinstance(name, str) and name.strip())


def can_refresh_repeated_read(
    tool_call: ToolCall,
    *,
    metadata: Mapping[str, object],
    read_only_tools: frozenset[str],
) -> bool:
    if tool_call.name not in read_only_tools:
        return False
    mutation_epoch = _integer(metadata.get("mutation_epoch"))
    read_epochs = _read_epochs(metadata)
    fingerprint_epoch = read_epochs.get(action_fingerprint(tool_call), 0)
    resource_epochs = _resource_epochs(metadata, "mutation_resource_epochs")
    verified_resources = _resource_epochs(metadata, "verified_resource_epochs")
    keys = _resource_keys(tool_call)
    if keys:
        if metadata.get("mutation_requires_global") is True:
            return mutation_epoch > fingerprint_epoch
        return any(
            resource_epochs.get(key, 0) > verified_resources.get(key, 0)
            for key in keys
        )
    return mutation_epoch > fingerprint_epoch


def record_tool_freshness(
    metadata: Mapping[str, object],
    tool_call: ToolCall,
    tool_result: ToolResult,
    *,
    read_only_tools: frozenset[str],
    mutation_tools: frozenset[str],
    observed_epoch: int | None = None,
) -> dict[str, object]:
    updated = dict(metadata)
    if (
        tool_result.status is not ToolCallStatus.EXECUTED
        or tool_result.metadata.get("client_effect_deferred") is True
    ):
        return updated
    if tool_call.name == "skills.read":
        skill_id = tool_result.metadata.get("skill_id")
        skill_name = tool_result.metadata.get("skill_name")
        skill_reads = updated.get("skill_reads")
        reads = dict(skill_reads) if isinstance(skill_reads, dict) else {}
        for value in (skill_id, skill_name):
            if isinstance(value, str) and value.strip():
                reads[value.strip()] = tool_result.metadata.get("skill_digest")
        updated["skill_reads"] = reads
    mutation_epoch = _integer(updated.get("mutation_epoch"))
    if tool_call.name in mutation_tools:
        next_epoch = mutation_epoch + 1
        updated["mutation_epoch"] = next_epoch
        resource_epochs = _resource_epochs(updated, "mutation_resource_epochs")
        resource_keys = _resource_keys(tool_call, tool_result.metadata)
        if not resource_keys:
            updated["mutation_requires_global"] = True
        for key in resource_keys or {f"tool:{tool_call.name}"}:
            resource_epochs[key] = next_epoch
        updated["mutation_resource_epochs"] = resource_epochs
        evidence_by_resource = _mutation_evidence(updated)
        for resource in _explicit_resource_refs(tool_result.metadata):
            evidence_by_resource[resource.key] = {
                "resource_ref": resource.model_dump(mode="json"),
                "mutation_effect_id": _metadata_text(
                    tool_result.metadata, "mutation_effect_id", "provider_operation_id"
                )
                or str(tool_call.tool_call_id),
                "host_receipt_ref": (
                    f"tool-receipt:{tool_call.tool_call_id}"
                    if tool_result.receipt is not None
                    else None
                ),
                "commit_version": _metadata_text(
                    tool_result.metadata, "commit_version", "business_revision"
                ),
            }
        if evidence_by_resource:
            updated["mutation_resource_evidence"] = evidence_by_resource
        updated["post_mutation_verification_prompted"] = False
        return updated
    if tool_call.name not in read_only_tools:
        return updated
    verified_epoch = mutation_epoch if observed_epoch is None else observed_epoch
    read_epochs = _read_epochs(updated)
    read_epochs[action_fingerprint(tool_call)] = verified_epoch
    updated["read_fingerprint_epochs"] = read_epochs
    resource_epochs = _resource_epochs(updated, "mutation_resource_epochs")
    verified_resources = _resource_epochs(updated, "verified_resource_epochs")
    explicit_resources = _explicit_resource_refs(tool_result.metadata)
    verified_any = False
    if explicit_resources:
        evidence_by_resource = _mutation_evidence(updated)
        evidence_records = _verification_evidence(updated)
        for resource in explicit_resources:
            mutation_epoch_for_resource = resource_epochs.get(resource.key)
            if mutation_epoch_for_resource is None:
                continue
            mutation = evidence_by_resource.get(resource.key, {})
            status = _verification_status(
                observed_epoch=verified_epoch,
                mutation_epoch=mutation_epoch_for_resource,
                commit_version=_optional_text(mutation.get("commit_version")),
                read_version=_metadata_text(
                    tool_result.metadata, "read_version", "business_revision"
                ),
                postcondition_met=tool_result.metadata.get("postcondition_met"),
            )
            evidence = VerificationEvidence(
                resource_ref=resource,
                mutation_effect_id=_optional_text(mutation.get("mutation_effect_id")),
                host_receipt_ref=_optional_text(mutation.get("host_receipt_ref")),
                commit_version=_optional_text(mutation.get("commit_version")),
                read_version=_metadata_text(
                    tool_result.metadata, "read_version", "business_revision"
                ),
                observed_epoch=verified_epoch,
                postcondition=_metadata_text(tool_result.metadata, "postcondition"),
                verification_status=status,
            )
            evidence_records.append(evidence.model_dump(mode="json"))
            if status is VerificationStatus.VERIFIED:
                verified_resources[resource.key] = mutation_epoch_for_resource
                verified_any = True
        updated["verification_evidence"] = evidence_records[-32:]
    else:
        for key in _resource_keys(tool_call, tool_result.metadata):
            if key in resource_epochs:
                verified_resources[key] = min(resource_epochs[key], verified_epoch)
                verified_any = True
    updated["verified_resource_epochs"] = verified_resources
    if (
        metadata.get("mutation_requires_global") is True
        or verified_any
        or not resource_epochs
    ):
        updated["verified_mutation_epoch"] = max(
            _integer(updated.get("verified_mutation_epoch")), verified_epoch
        )
    return updated


def needs_post_mutation_verification(
    metadata: Mapping[str, object],
    *,
    read_only_tools: frozenset[str],
) -> bool:
    if not read_only_tools:
        return False
    mutation_epochs = _resource_epochs(metadata, "mutation_resource_epochs")
    verified_epochs = _resource_epochs(metadata, "verified_resource_epochs")
    if mutation_epochs and metadata.get("mutation_requires_global") is not True:
        return any(
            epoch > verified_epochs.get(resource, 0)
            for resource, epoch in mutation_epochs.items()
        )
    return _integer(metadata.get("mutation_epoch")) > _integer(
        metadata.get("verified_mutation_epoch")
    )


def post_mutation_verification_instruction(*, created_at: datetime) -> SessionMessage:
    return SessionMessage(
        message_id=new_message_id(),
        role=MessageRole.USER,
        content=(
            "Before finishing, verify the current state with an available read-only tool. "
            "Use fresh evidence obtained after the mutation, reconcile it with earlier "
            "results, then provide the final answer."
        ),
        created_at=created_at,
    )


def should_prompt_post_mutation_verification(
    metadata: Mapping[str, object],
    *,
    can_verify: bool,
    read_only_tools: frozenset[str],
) -> bool:
    return (
        can_verify
        and needs_post_mutation_verification(metadata, read_only_tools=read_only_tools)
        and metadata.get("post_mutation_verification_prompted") is not True
    )


def _read_epochs(metadata: Mapping[str, object]) -> dict[str, int]:
    raw = metadata.get("read_fingerprint_epochs")
    if not isinstance(raw, dict):
        return {}
    return {
        str(key): value
        for key, value in raw.items()
        if isinstance(value, int) and not isinstance(value, bool) and value >= 0
    }


def _resource_epochs(metadata: Mapping[str, object], key: str) -> dict[str, int]:
    raw = metadata.get(key)
    if not isinstance(raw, dict):
        return {}
    return {
        str(resource): epoch
        for resource, epoch in raw.items()
        if isinstance(resource, str)
        and resource.strip()
        and isinstance(epoch, int)
        and not isinstance(epoch, bool)
        and epoch >= 0
    }


def _resource_keys(
    tool_call: ToolCall,
    result_metadata: Mapping[str, object] | None = None,
) -> set[str]:
    explicit = _explicit_resource_keys(result_metadata)
    if explicit:
        return explicit
    if result_metadata and result_metadata.get("route") == "host_tool_gateway":
        return set()
    values: dict[str, object] = dict(tool_call.arguments)
    if result_metadata:
        values.update(result_metadata)
    keys: set[str] = set()
    for name, value in values.items():
        if not isinstance(value, str | int) or isinstance(value, bool):
            continue
        normalized = name.lower()
        if normalized.endswith("_id") or normalized in {"url", "path", "name"}:
            text = str(value).strip()
            if text:
                keys.add(f"{normalized}:{text[:512]}")
    return keys


def _explicit_resource_keys(
    result_metadata: Mapping[str, object] | None,
) -> set[str]:
    return {resource.key for resource in _explicit_resource_refs(result_metadata)}


def _explicit_resource_refs(
    result_metadata: Mapping[str, object] | None,
) -> tuple[VerificationResourceRef, ...]:
    if not result_metadata:
        return ()
    raw_refs = result_metadata.get("verification_resource_refs")
    if raw_refs is None:
        single = result_metadata.get("verification_resource_ref")
        raw_refs = (single,) if single is not None else ()
    if not isinstance(raw_refs, list | tuple):
        return ()
    refs: list[VerificationResourceRef] = []
    for raw in raw_refs:
        if not isinstance(raw, Mapping):
            continue
        try:
            refs.append(VerificationResourceRef.model_validate(raw))
        except ValueError:
            continue
    return tuple(refs)


def _mutation_evidence(metadata: Mapping[str, object]) -> dict[str, dict[str, object]]:
    raw = metadata.get("mutation_resource_evidence")
    if not isinstance(raw, dict):
        return {}
    return {
        str(key): dict(value)
        for key, value in raw.items()
        if isinstance(key, str) and isinstance(value, dict)
    }


def _verification_evidence(metadata: Mapping[str, object]) -> list[dict[str, object]]:
    raw = metadata.get("verification_evidence")
    if not isinstance(raw, list):
        return []
    return [dict(item) for item in raw if isinstance(item, dict)]


def _verification_status(
    *,
    observed_epoch: int,
    mutation_epoch: int,
    commit_version: str | None,
    read_version: str | None,
    postcondition_met: object,
) -> VerificationStatus:
    if observed_epoch < mutation_epoch:
        return VerificationStatus.STALE
    if postcondition_met is False:
        return VerificationStatus.FAILED
    if commit_version is not None and read_version != commit_version:
        return VerificationStatus.UNVERIFIED
    return VerificationStatus.VERIFIED


def _metadata_text(metadata: Mapping[str, object], *keys: str) -> str | None:
    for key in keys:
        value = metadata.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()[:512]
    return None


def _optional_text(value: object) -> str | None:
    return value.strip()[:512] if isinstance(value, str) and value.strip() else None


def _integer(value: object) -> int:
    return value if isinstance(value, int) and not isinstance(value, bool) else 0
