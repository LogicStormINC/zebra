"""Track whether successful mutations have fresh read evidence."""

from collections.abc import Mapping
from datetime import datetime

from agent_core.domain.identifiers import new_message_id
from agent_core.domain.messages import MessageRole, SessionMessage
from agent_core.domain.tools import ToolCall, ToolCallStatus, ToolResult
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
        resource_keys = _resource_keys(tool_call)
        if not resource_keys:
            updated["mutation_requires_global"] = True
        for key in resource_keys or {f"tool:{tool_call.name}"}:
            resource_epochs[key] = next_epoch
        updated["mutation_resource_epochs"] = resource_epochs
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
    for key in _resource_keys(tool_call, tool_result.metadata):
        if key in resource_epochs:
            verified_resources[key] = resource_epochs[key]
    updated["verified_resource_epochs"] = verified_resources
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


def _integer(value: object) -> int:
    return value if isinstance(value, int) and not isinstance(value, bool) else 0
