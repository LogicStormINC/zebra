from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

from agent_core.application import (
    attachment_refs_from_event,
    task_workspace_image_prompt_suffix,
)
from agent_core.domain.attachments import AttachmentContextInput, SessionAttachmentRef
from agent_core.domain.context_capsule import ContextCapsule
from agent_core.domain.events import EventType, SessionEvent
from agent_core.domain.model_media import ModelMediaInput
from agent_core.domain.session_history import normalize_history_session_ids
from agent_core.domain.tool_profiles import ToolProfile
from agent_core.domain.workspaces import WorkspaceProjection
from agent_core.ports.context_compiler import RuntimeEvidenceInput
from agent_security import NetworkProfile, PolicyProfile, parse_network_profile
from agent_storage import SQLiteArtifactPayloadStore, load_attachment_contexts
from agent_storage.session_attachments import RegisteredTaskMedia, TaskAttachmentMediaResolver


@dataclass(frozen=True)
class RecoveredTask:
    title: str
    user_input: str
    workspace_root: Path
    policy_profile: str
    tool_profile: ToolProfile
    network_profile: NetworkProfile
    mcp_allowlist: tuple[str, ...] | None
    skill_components: tuple[str, ...] | None
    history_session_ids: tuple[str, ...] | None
    max_attempts: int
    max_model_calls: int | None
    max_tool_calls: int | None
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
    legacy_image_prompt_suffix = _task_image_context_suffix(user_input, task_image_refs)
    title = task_payload.get("title")
    resolved_title = title.strip() if isinstance(title, str) and title.strip() else fallback_title
    policy_profile = workspace.policy_profile or PolicyProfile.WORKSPACE_WRITE.value
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
        skill_components=workspace.skill_components,
        history_session_ids=_history_session_ids(task_payload.get("history_session_ids")),
        max_attempts=_optional_positive_int(task_payload.get("max_attempts")) or 1,
        max_model_calls=_optional_positive_int(task_payload.get("max_model_calls")),
        max_tool_calls=_optional_positive_int(task_payload.get("max_tool_calls")),
        attachments=attachments,
        legacy_image_prompt_suffix=legacy_image_prompt_suffix,
        media_inputs=media_resolver.media_inputs,
        media_resolver=media_resolver,
        runtime_evidence=(
            *_context_capsule_evidence(events, active_capsule=active_capsule),
            *((handoff_evidence,) if handoff_evidence is not None else ()),
        ),
    )


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
