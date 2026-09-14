from __future__ import annotations

from datetime import datetime
from typing import TypedDict

from agent_core.domain.attachments import TextAttachmentInput
from agent_core.domain.identifiers import AgentDefinitionId
from agent_core.domain.image_attachments import ImageAttachmentInput
from agent_core.domain.turns import InteractionMode
from agent_core.domain.workspace_control import WorkspaceSource


class CreateSessionPayload(TypedDict):
    prompt: str
    title: str
    workspace: str
    workspace_source: WorkspaceSource | None
    execute: bool
    policy_profile: str
    tool_profile: str
    max_model_calls: int | None
    max_tool_calls: int | None
    network_profile: str
    network_allowlist: list[str]
    mcp_allowlist: list[str]
    skill_components: list[str]
    mcp_resource_ids: list[str]
    mcp_prompt_id: str | None
    mcp_prompt_arguments: dict[str, str]
    history_session_ids: tuple[str, ...] | None
    attachments: tuple[TextAttachmentInput | ImageAttachmentInput, ...]
    definition_id: AgentDefinitionId | None
    definition_environment: str | None
    interaction_mode: InteractionMode | None
    model_profile: str | None
    reasoning_effort: str | None


class ResumeSessionPayload(TypedDict):
    worker_id: str
    lease_ttl_seconds: int


class SuspendSessionPayload(TypedDict):
    pass


class CancelSessionPayload(TypedDict):
    pass


class AppendSessionMessagePayload(TypedDict):
    content: str
    clarification_id: str | None
    attachments: tuple[TextAttachmentInput | ImageAttachmentInput, ...]
    model_profile: str | None
    reasoning_effort: str | None


class ApprovalDecisionPayload(TypedDict):
    operator: str
    reason: str


class BulkMemoryReviewPayload(TypedDict):
    decision: str
    operator: str
    reason: str
    memory_ids: list[str]


class CommitSessionPayload(TypedDict):
    message: str
    author_name: str
    author_email: str


class PullRequestPayload(TypedDict):
    title: str
    body: str
    base_branch: str
    head_branch: str | None
    dry_run: bool


class MemoryOverviewPayload(TypedDict):
    user_id: str | None
    tenant_id: str | None
    as_of: datetime | None


class QueueSweepPreviewPayload(TypedDict):
    decision: str
    memory_type: str | None
