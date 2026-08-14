from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

from agent_core.application import (
    attachment_refs_from_event,
    task_workspace_image_prompt_suffix,
)
from agent_core.domain.agent_definitions import AgentDefinition
from agent_core.domain.attachments import AttachmentContextInput, SessionAttachmentRef
from agent_core.domain.attempt_policy import TaskAttemptPolicy
from agent_core.domain.context_capsule import ContextCapsule
from agent_core.domain.events import EventType, SessionEvent
from agent_core.domain.model_media import ModelMediaInput
from agent_core.domain.session_history import normalize_history_session_ids
from agent_core.domain.skills import SkillComponentIdentity
from agent_core.domain.tool_profiles import ToolProfile
from agent_core.domain.workspaces import WorkspaceProjection
from agent_core.ports.agent_tasks import TaskEvent
from agent_core.ports.context_compiler import RuntimeEvidenceInput
from agent_security import NetworkProfile, PolicyProfile, parse_network_profile
from agent_storage import SQLiteArtifactPayloadStore, load_attachment_contexts
from agent_storage.session_attachments import RegisteredTaskMedia, TaskAttachmentMediaResolver

from zebra_agent_worker.task_frozen_policy import (
    TaskFrozenFacts,
    _check_segment_against_facts,
    _merge_fact,
    _strict_optional,
    _strict_reasons,
    _strict_text,
)


@dataclass(frozen=True)
class RecoveredTask:
    title: str
    user_input: str
    workspace_root: Path
    policy_profile: str
    tool_profile: ToolProfile
    network_profile: NetworkProfile
    mcp_allowlist: tuple[str, ...] | None
    preapproved_readonly_tools: tuple[str, ...] | None
    skill_components: tuple[str, ...] | None
    skill_component_identities: tuple[SkillComponentIdentity, ...] | None
    agent_definition: AgentDefinition | None
    history_session_ids: tuple[str, ...] | None
    max_attempts: int
    max_corrections_per_attempt: int
    execution_profile_id: str | None
    retryable_stop_reasons: tuple[str, ...]
    max_model_calls: int | None
    max_tool_calls: int | None
    model_id: str | None
    attachments: tuple[AttachmentContextInput, ...]
    legacy_image_prompt_suffix: str
    media_inputs: tuple[ModelMediaInput, ...]
    media_resolver: TaskAttachmentMediaResolver
    runtime_evidence: tuple[RuntimeEvidenceInput, ...]


def recover_task(
    events: list[SessionEvent],
    *,
    workspace: WorkspaceProjection,
    fallback_title: str,
    attachment_store: SQLiteArtifactPayloadStore,
    task_image_refs: tuple[SessionAttachmentRef, ...] = (),
    registered_task_media: tuple[RegisteredTaskMedia, ...] = (),
    active_capsule: ContextCapsule | None = None,
    handoff_evidence: RuntimeEvidenceInput | None = None,
    task_model_id: str | None = None,
    task_facts: TaskFrozenFacts | None = None,
) -> RecoveredTask:
    user_input: str | None = None
    task_payload: dict[str, object] | None = None
    user_event: SessionEvent | None = None
    for event in events:
        if event.event_type is EventType.USER_MESSAGE_RECEIVED:
            content = event.payload.get("content")
            if isinstance(content, str) and content.strip():
                user_input = content.strip()
                user_event = event
        if event.event_type is EventType.TASK_PREPARED:
            task_payload = event.payload
    if user_input is None or user_event is None or task_payload is None:
        raise ValueError("queued session is missing bootstrap task input")
    model_id = _model_id(task_payload.get("model_id"))
    root_model_id = _model_id(task_model_id)
    if model_id is not None and root_model_id is not None and model_id != root_model_id:
        raise ValueError("queued session model selection drift detected")
    model_id = model_id or root_model_id
    agent_definition = _agent_definition_from_payload(task_payload.get("agent_definition"))
    if agent_definition != workspace.agent_definition:
        raise ValueError("queued session agent_definition drift detected")
    legacy_image_prompt_suffix = _task_image_context_suffix(user_input, task_image_refs)
    title = task_payload.get("title")
    resolved_title = title.strip() if isinstance(title, str) and title.strip() else fallback_title
    policy_profile = workspace.policy_profile or PolicyProfile.WORKSPACE_WRITE.value
    attempt_policy, max_model_calls, max_tool_calls = _task_facts_for_segment(
        task_payload, task_facts
    )
    try:
        attachments = load_attachment_contexts(
            attachment_store,
            attachment_refs_from_event(user_event),
        )
    except (FileNotFoundError, ValueError) as exc:
        raise ValueError(f"queued session attachment recovery failed: {exc}") from exc
    media_resolver = TaskAttachmentMediaResolver(attachment_store, registered_task_media)
    return RecoveredTask(
        title=resolved_title,
        user_input=user_input,
        workspace_root=Path(workspace.workspace_root).expanduser().resolve(),
        policy_profile=policy_profile,
        tool_profile=workspace.tool_profile,
        network_profile=parse_network_profile(
            workspace.network_profile,
            domain_allowlist=workspace.network_allowlist,
        ),
        mcp_allowlist=workspace.mcp_allowlist,
        preapproved_readonly_tools=workspace.preapproved_readonly_tools,
        skill_components=workspace.skill_components,
        skill_component_identities=workspace.skill_component_identities,
        agent_definition=agent_definition,
        history_session_ids=_history_session_ids(task_payload.get("history_session_ids")),
        max_attempts=attempt_policy.max_attempts,
        max_corrections_per_attempt=attempt_policy.max_corrections_per_attempt,
        execution_profile_id=attempt_policy.execution_profile_id,
        retryable_stop_reasons=attempt_policy.retryable_stop_reasons,
        max_model_calls=max_model_calls,
        max_tool_calls=max_tool_calls,
        model_id=model_id,
        attachments=attachments,
        legacy_image_prompt_suffix=legacy_image_prompt_suffix,
        media_inputs=media_resolver.media_inputs,
        media_resolver=media_resolver,
        runtime_evidence=(
            *_context_capsule_evidence(events, active_capsule=active_capsule),
            *((handoff_evidence,) if handoff_evidence is not None else ()),
        ),
    )


def persisted_task_model_id(events: list[SessionEvent]) -> str | None:
    selected: str | None = None
    for event in events:
        if event.event_type is not EventType.TASK_PREPARED:
            continue
        model_id = _model_id(event.payload.get("model_id"))
        if model_id is None:
            continue
        if selected is not None and selected != model_id:
            raise ValueError("task model selection drift detected")
        selected = model_id
    return selected


def _task_image_context_suffix(
    user_input: str,
    attachments: tuple[SessionAttachmentRef, ...],
) -> str:
    paths = tuple(
        (attachment.workspace_path, attachment.media_type)
        for attachment in attachments
        if attachment.storage_kind == "task_workspace"
        and attachment.workspace_path is not None
        and attachment.workspace_path not in user_input
    )
    return task_workspace_image_prompt_suffix(paths)


def _history_session_ids(value: object) -> tuple[str, ...] | None:
    if value is None:
        return None
    if not isinstance(value, list):
        raise ValueError("queued session history_session_ids must be a list")
    return normalize_history_session_ids(value)


def _context_capsule_evidence(
    events: list[SessionEvent],
    *,
    active_capsule: ContextCapsule | None = None,
) -> tuple[RuntimeEvidenceInput, ...]:
    if active_capsule is not None:
        return (_capsule_evidence(active_capsule, events=events),)
    for event in reversed(events):
        if event.event_type is not EventType.CONTEXT_COMPACTED:
            continue
        raw = event.payload.get("capsule")
        if not isinstance(raw, dict):
            continue
        capsule = ContextCapsule.model_validate(raw)
        return (_capsule_evidence(capsule, events=events),)
    return ()


def _capsule_evidence(
    capsule: ContextCapsule,
    *,
    events: list[SessionEvent],
) -> RuntimeEvidenceInput:
    return RuntimeEvidenceInput(
        kind="conversation_summary",
        summary=capsule.objective,
        details=(
            *capsule.constraints,
            *capsule.decisions,
            *capsule.plan,
            *_exact_tail_details(capsule, events),
            f"Immediate next: {capsule.immediate_next}",
        ),
        metadata={
            "capsule_id": capsule.capsule_id,
            "capsule_version": capsule.version,
            "source_hash": capsule.source_hash,
            "profile": capsule.profile,
            "pending_tools": [tool.model_dump(mode="json") for tool in capsule.pending_tools],
            "artifact_refs": list(capsule.artifact_refs),
        },
    )


def _exact_tail_details(
    capsule: ContextCapsule,
    events: list[SessionEvent],
) -> tuple[str, ...]:
    by_sequence = {event.sequence: event for event in events}
    details: list[str] = []
    for reference in capsule.recent_exact_tail_refs:
        if not reference.startswith("event://"):
            continue
        _, _, sequence_text = reference.rpartition("/")
        try:
            event = by_sequence.get(int(sequence_text))
        except ValueError:
            continue
        if event is None:
            continue
        payload = json.dumps(event.payload, sort_keys=True, ensure_ascii=False)[:2_000]
        details.append(f"Exact tail event {event.sequence} {event.event_type.value}: {payload}")
    return tuple(details)


def _optional_positive_int(value: object) -> int | None:
    if not isinstance(value, int) or isinstance(value, bool):
        return None
    return value if value > 0 else None


def _attempt_policy_from_payload(payload: dict[str, object]) -> TaskAttemptPolicy:
    """Reconstruct the frozen Task policy strictly: present fields must be
    valid (no silent fallback to defaults); only absent legacy fields get
    defaults; a present ``None`` (model-dump convention) counts as absent."""
    try:
        return TaskAttemptPolicy(
            max_attempts=(
                _strict_optional(payload.get("max_attempts"), "max_attempts", positive=True)
                if "max_attempts" in payload
                else 1
            )
            or 1,
            max_corrections_per_attempt=(
                _strict_optional(
                    payload.get("max_corrections_per_attempt"),
                    "max_corrections_per_attempt",
                    non_negative=True,
                )
                if "max_corrections_per_attempt" in payload
                else 0
            )
            or 0,
            execution_profile_id=(
                _strict_text(payload.get("execution_profile_id"), "execution_profile_id")
                if "execution_profile_id" in payload
                else None
            ),
            retryable_stop_reasons=(
                parsed_reasons
                if (parsed_reasons := _strict_reasons(payload.get("retryable_stop_reasons")))
                is not None
                else TaskAttemptPolicy().retryable_stop_reasons
            ),
        )
    except ValueError as exc:
        raise ValueError(f"queued session attempt policy is invalid: {exc}") from exc


def task_frozen_facts(task_events: list[TaskEvent] | tuple[TaskEvent, ...]) -> TaskFrozenFacts:
    """Recover the frozen policy + call budgets from the ordered Stable Task
    TASK_PREPARED facts (root authority). Present fields must agree across
    facts; drift or corruption fails closed; the first/root TASK_PREPARED
    establishes the value - absent fields freeze the legacy defaults, so a
    later child can never expand them."""
    max_attempts: int | None = None
    corrections: int | None = None
    profile_id: str | None = None
    reasons: tuple[str, ...] | None = None
    max_model_calls: int | None = None
    max_tool_calls: int | None = None
    first_fact_seen = False
    for item in task_events:
        if item.event.event_type is not EventType.TASK_PREPARED:
            continue
        payload = item.event.payload
        if not first_fact_seen:
            first_fact_seen = True
            max_attempts = (
                _strict_optional(payload.get("max_attempts"), "max_attempts", positive=True)
                if "max_attempts" in payload
                else 1
            ) or 1
            corrections = (
                _strict_optional(
                    payload.get("max_corrections_per_attempt"),
                    "max_corrections_per_attempt",
                    non_negative=True,
                )
                if "max_corrections_per_attempt" in payload
                else 0
            ) or 0
            profile_id = (
                _strict_text(payload.get("execution_profile_id"), "execution_profile_id")
                if "execution_profile_id" in payload
                else None
            )
            reasons = (
                _strict_reasons(payload.get("retryable_stop_reasons"))
                if "retryable_stop_reasons" in payload
                else TaskAttemptPolicy().retryable_stop_reasons
            )
            max_model_calls = (
                _strict_optional(payload.get("max_model_calls"), "max_model_calls", positive=True)
                if "max_model_calls" in payload
                else None
            )
            max_tool_calls = (
                _strict_optional(payload.get("max_tool_calls"), "max_tool_calls", positive=True)
                if "max_tool_calls" in payload
                else None
            )
            continue
        value: object = _strict_optional(payload.get("max_attempts"), "max_attempts", positive=True)
        max_attempts = _merge_fact(max_attempts, value, "max_attempts")
        value = _strict_optional(
            payload.get("max_corrections_per_attempt"),
            "max_corrections_per_attempt",
            non_negative=True,
        )
        corrections = _merge_fact(corrections, value, "max_corrections_per_attempt")
        value = _strict_text(payload.get("execution_profile_id"), "execution_profile_id")
        profile_id = _merge_fact(profile_id, value, "execution_profile_id")
        value = _strict_reasons(payload.get("retryable_stop_reasons"))
        reasons = _merge_fact(reasons, value, "retryable_stop_reasons")
        value = _strict_optional(payload.get("max_model_calls"), "max_model_calls", positive=True)
        max_model_calls = _merge_fact(max_model_calls, value, "max_model_calls")
        value = _strict_optional(payload.get("max_tool_calls"), "max_tool_calls", positive=True)
        max_tool_calls = _merge_fact(max_tool_calls, value, "max_tool_calls")
    policy = TaskAttemptPolicy(
        max_attempts=max_attempts if max_attempts is not None else 1,
        max_corrections_per_attempt=corrections if corrections is not None else 0,
        execution_profile_id=profile_id,
        retryable_stop_reasons=(
            reasons if reasons is not None else TaskAttemptPolicy().retryable_stop_reasons
        ),
    )
    return TaskFrozenFacts(
        policy=policy,
        max_model_calls=max_model_calls,
        max_tool_calls=max_tool_calls,
    )


def _task_facts_for_segment(
    payload: dict[str, object],
    task_facts: TaskFrozenFacts | None,
) -> tuple[TaskAttemptPolicy, int | None, int | None]:
    if task_facts is None:
        policy = _attempt_policy_from_payload(payload)
        return (
            policy,
            (
                _strict_optional(payload.get("max_model_calls"), "max_model_calls", positive=True)
                if "max_model_calls" in payload
                else None
            ),
            (
                _strict_optional(payload.get("max_tool_calls"), "max_tool_calls", positive=True)
                if "max_tool_calls" in payload
                else None
            ),
        )
    _check_segment_against_facts(payload, task_facts)
    return task_facts.policy, task_facts.max_model_calls, task_facts.max_tool_calls


def _optional_non_negative_int(value: object) -> int:
    if value is None:
        return 0
    if not isinstance(value, int) or isinstance(value, bool) or value < 0:
        raise ValueError("max_corrections_per_attempt must be a non-negative integer")
    return value


def _optional_text(value: object) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str):
        raise ValueError("execution_profile_id must be a string")
    return value.strip() or None


def _optional_reasons(value: object) -> tuple[str, ...]:
    if value is None:
        return TaskAttemptPolicy().retryable_stop_reasons
    if not isinstance(value, list):
        raise ValueError("retryable_stop_reasons must be a list")
    reasons: list[str] = []
    for item in value:
        if not isinstance(item, str) or not item.strip():
            raise ValueError("retryable_stop_reasons must be non-blank codes")
        if item.strip() not in reasons:
            reasons.append(item.strip())
    return tuple(reasons)


def _model_id(value: object) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str) or not value.strip():
        raise ValueError("queued session contains invalid model selection")
    return value.strip()


def _agent_definition_from_payload(value: object) -> AgentDefinition | None:
    if value is None:
        return None
    if not isinstance(value, dict):
        raise ValueError("queued session contains invalid agent_definition")
    try:
        return AgentDefinition.model_validate(value)
    except ValueError as exc:
        raise ValueError("queued session contains invalid agent_definition") from exc
