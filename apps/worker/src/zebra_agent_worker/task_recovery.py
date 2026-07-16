from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from agent_core.application import attachment_refs_from_event
from agent_core.domain.attachments import AttachmentContextInput
from agent_core.domain.events import EventType, SessionEvent
from agent_core.domain.tool_profiles import ToolProfile
from agent_core.domain.workspaces import WorkspaceProjection
from agent_security import NetworkProfile, PolicyProfile, parse_network_profile
from agent_storage import SQLiteArtifactPayloadStore, load_attachment_contexts


@dataclass(frozen=True)
class RecoveredTask:
    title: str
    user_input: str
    workspace_root: Path
    policy_profile: str
    tool_profile: ToolProfile
    network_profile: NetworkProfile
    mcp_allowlist: tuple[str, ...] | None
    max_attempts: int
    max_model_calls: int | None
    max_tool_calls: int | None
    attachments: tuple[AttachmentContextInput, ...]


def recover_task(
    events: list[SessionEvent],
    *,
    workspace: WorkspaceProjection,
    fallback_title: str,
    attachment_store: SQLiteArtifactPayloadStore,
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
        max_attempts=_optional_positive_int(task_payload.get("max_attempts")) or 1,
        max_model_calls=_optional_positive_int(task_payload.get("max_model_calls")),
        max_tool_calls=_optional_positive_int(task_payload.get("max_tool_calls")),
        attachments=attachments,
    )


def _optional_positive_int(value: object) -> int | None:
    if not isinstance(value, int) or isinstance(value, bool):
        return None
    return value if value > 0 else None
