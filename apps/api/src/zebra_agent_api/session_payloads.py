from __future__ import annotations

from datetime import UTC, datetime
from typing import TypedDict

from agent_core.domain.attachments import TextAttachmentInput
from agent_core.domain.mcp import normalize_mcp_allowlist
from agent_core.domain.memories import MemoryType
from agent_core.domain.networking import NetworkProfileName
from agent_core.domain.session_history import normalize_history_session_ids
from agent_core.domain.tool_profiles import ToolProfile
from agent_runtime import normalize_mcp_resource_ids
from agent_security import NetworkProfileError, PolicyProfile, parse_network_profile

from zebra_agent_api.responses import ApiResponse, bad_request
from zebra_agent_api.session_attachment_inputs import parse_attachment_inputs


class CreateSessionPayload(TypedDict):
    prompt: str
    title: str
    workspace: str
    execute: bool
    policy_profile: str
    tool_profile: str
    network_profile: str
    network_allowlist: list[str]
    mcp_allowlist: list[str]
    mcp_resource_ids: list[str]
    mcp_prompt_id: str | None
    mcp_prompt_arguments: dict[str, str]
    history_session_ids: tuple[str, ...] | None
    attachments: tuple[TextAttachmentInput, ...]


CREATE_SESSION_FIELDS = frozenset(CreateSessionPayload.__annotations__)


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
    attachments: tuple[TextAttachmentInput, ...]


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


def parse_create_session_payload(
    payload: dict[str, object],
) -> CreateSessionPayload | ApiResponse:
    unknown_fields = sorted(payload.keys() - CREATE_SESSION_FIELDS)
    if unknown_fields:
        return bad_request(f"unknown create-session fields: {', '.join(unknown_fields)}")
    prompt = payload.get("prompt")
    if not isinstance(prompt, str) or not prompt.strip():
        return bad_request("prompt must be a non-blank string")

    title = payload.get("title", "Untitled task")
    if not isinstance(title, str) or not title.strip():
        return bad_request("title must be a non-blank string when provided")

    workspace = payload.get("workspace", ".")
    if not isinstance(workspace, str) or not workspace.strip():
        return bad_request("workspace must be a non-blank string when provided")

    execute = payload.get("execute", False)
    if not isinstance(execute, bool):
        return bad_request("execute must be a boolean when provided")

    policy_profile = payload.get("policy_profile", PolicyProfile.WORKSPACE_WRITE.value)
    if not isinstance(policy_profile, str):
        return bad_request("policy_profile must be a string when provided")
    try:
        PolicyProfile(policy_profile)
    except ValueError:
        return bad_request("policy_profile is not supported")

    tool_profile = payload.get("tool_profile", ToolProfile.GENERAL.value)
    if not isinstance(tool_profile, str):
        return bad_request("tool_profile must be a string when provided")
    try:
        ToolProfile(tool_profile)
    except ValueError:
        return bad_request("tool_profile is not supported")

    network_profile = payload.get("network_profile", "none")
    network_allowlist = payload.get("network_allowlist", [])
    if not isinstance(network_profile, str):
        return bad_request("network_profile must be a string when provided")
    if not isinstance(network_allowlist, list) or not all(
        isinstance(item, str) for item in network_allowlist
    ):
        return bad_request("network_allowlist must be a list of strings when provided")
    try:
        network = parse_network_profile(network_profile, domain_allowlist=network_allowlist)
    except NetworkProfileError as exc:
        return bad_request(str(exc))
    try:
        attachments = parse_attachment_inputs(payload.get("attachments"))
    except ValueError as exc:
        return bad_request(str(exc))
    raw_history_session_ids = payload.get("history_session_ids")
    if raw_history_session_ids is not None and (
        not isinstance(raw_history_session_ids, list)
        or not all(isinstance(item, str) for item in raw_history_session_ids)
    ):
        return bad_request("history_session_ids must be a list of UUID strings when provided")
    try:
        history_session_ids = (
            None
            if raw_history_session_ids is None
            else normalize_history_session_ids(raw_history_session_ids)
        )
    except ValueError as exc:
        return bad_request(str(exc))
    mcp_allowlist = payload.get("mcp_allowlist", [])
    if not isinstance(mcp_allowlist, list) or not all(
        isinstance(item, str) for item in mcp_allowlist
    ):
        return bad_request("mcp_allowlist must be a list of strings when provided")
    try:
        normalized_mcp = normalize_mcp_allowlist(mcp_allowlist)
    except ValueError as exc:
        return bad_request(str(exc))
    mcp_resource_ids = payload.get("mcp_resource_ids", [])
    if not isinstance(mcp_resource_ids, list) or not all(
        isinstance(item, str) for item in mcp_resource_ids
    ):
        return bad_request("mcp_resource_ids must be a list of strings when provided")
    try:
        normalized_resources = normalize_mcp_resource_ids(mcp_resource_ids)
    except ValueError as exc:
        return bad_request(str(exc))
    mcp_prompt_id = payload.get("mcp_prompt_id")
    if mcp_prompt_id is not None and (
        not isinstance(mcp_prompt_id, str) or not mcp_prompt_id.strip()
    ):
        return bad_request("mcp_prompt_id must be a non-blank string when provided")
    normalized_prompt_id = mcp_prompt_id.strip() if isinstance(mcp_prompt_id, str) else None
    raw_prompt_arguments = payload.get("mcp_prompt_arguments", {})
    if not isinstance(raw_prompt_arguments, dict) or not all(
        isinstance(key, str) and isinstance(value, str)
        for key, value in raw_prompt_arguments.items()
    ):
        return bad_request("mcp_prompt_arguments must be an object of string values")
    if raw_prompt_arguments and normalized_prompt_id is None:
        return bad_request("mcp_prompt_arguments require mcp_prompt_id")
    if (normalized_mcp or normalized_resources or normalized_prompt_id) and network.name not in {
        NetworkProfileName.MCP_PROXY_ONLY,
        NetworkProfileName.FULL_TRUSTED_LOCAL,
    }:
        return bad_request("MCP selections require an MCP-capable network profile")

    return {
        "prompt": prompt.strip(),
        "title": title.strip(),
        "workspace": workspace.strip(),
        "execute": execute,
        "policy_profile": policy_profile,
        "tool_profile": tool_profile,
        "network_profile": network.name.value,
        "network_allowlist": list(network.domain_allowlist),
        "mcp_allowlist": list(normalized_mcp),
        "mcp_resource_ids": list(normalized_resources),
        "mcp_prompt_id": normalized_prompt_id,
        "mcp_prompt_arguments": dict(raw_prompt_arguments),
        "history_session_ids": history_session_ids,
        "attachments": attachments,
    }


def parse_resume_session_payload(
    payload: dict[str, object],
) -> ResumeSessionPayload | ApiResponse:
    worker_id = payload.get("worker_id", "local-worker")
    if not isinstance(worker_id, str) or not worker_id.strip():
        return bad_request("worker_id must be a non-blank string when provided")

    lease_ttl_seconds = payload.get("lease_ttl_seconds", 30)
    if not isinstance(lease_ttl_seconds, int) or isinstance(lease_ttl_seconds, bool):
        return bad_request("lease_ttl_seconds must be an integer when provided")
    if lease_ttl_seconds <= 0:
        return bad_request("lease_ttl_seconds must be greater than zero")

    return {
        "worker_id": worker_id.strip(),
        "lease_ttl_seconds": lease_ttl_seconds,
    }


def parse_suspend_session_payload(
    payload: dict[str, object],
) -> SuspendSessionPayload | ApiResponse:
    if payload:
        return bad_request("suspend does not accept request fields yet")
    return {}


def parse_cancel_session_payload(
    payload: dict[str, object],
) -> CancelSessionPayload | ApiResponse:
    if payload:
        return bad_request("cancel does not accept request fields yet")
    return {}


def parse_append_session_message_payload(
    payload: dict[str, object],
) -> AppendSessionMessagePayload | ApiResponse:
    content = payload.get("content")
    if not isinstance(content, str) or not content.strip():
        return bad_request("content must be a non-blank string")
    clarification_id = payload.get("clarification_id")
    if clarification_id is not None and (
        not isinstance(clarification_id, str) or not clarification_id.strip()
    ):
        return bad_request("clarification_id must be a non-blank string when provided")
    try:
        attachments = parse_attachment_inputs(payload.get("attachments"))
    except ValueError as exc:
        return bad_request(str(exc))
    if clarification_id is not None and attachments:
        return bad_request("clarification responses do not accept attachments")
    return {
        "content": content.strip(),
        "clarification_id": clarification_id.strip() if clarification_id else None,
        "attachments": attachments,
    }


def parse_approval_decision_payload(
    payload: dict[str, object],
    *,
    default_reason: str,
) -> ApprovalDecisionPayload | ApiResponse:
    operator = payload.get("operator", "api-operator")
    if not isinstance(operator, str) or not operator.strip():
        return bad_request("operator must be a non-blank string when provided")

    reason = payload.get("reason", default_reason)
    if not isinstance(reason, str) or not reason.strip():
        return bad_request("reason must be a non-blank string when provided")

    return {
        "operator": operator.strip(),
        "reason": reason.strip(),
    }


def parse_bulk_memory_review_payload(
    payload: dict[str, object],
) -> BulkMemoryReviewPayload | ApiResponse:
    decision = payload.get("decision")
    if decision not in {"confirm", "expire"}:
        return bad_request("decision must be either 'confirm' or 'expire'")

    parsed = parse_approval_decision_payload(
        payload,
        default_reason=f"{decision} via API",
    )
    if isinstance(parsed, ApiResponse):
        return parsed

    memory_ids = payload.get("memory_ids")
    if not isinstance(memory_ids, list) or not memory_ids:
        return bad_request("memory_ids must be a non-empty list of memory ids")

    normalized_memory_ids: list[str] = []
    for memory_id in memory_ids:
        if not isinstance(memory_id, str) or not memory_id.strip():
            return bad_request("memory_ids must contain non-blank strings")
        normalized_memory_ids.append(memory_id.strip())

    return {
        "decision": decision,
        "operator": parsed["operator"],
        "reason": parsed["reason"],
        "memory_ids": normalized_memory_ids,
    }


def parse_commit_session_payload(
    payload: dict[str, object],
) -> CommitSessionPayload | ApiResponse:
    message = payload.get("message")
    if not isinstance(message, str) or not message.strip():
        return bad_request("message must be a non-blank string")

    author_name = payload.get("author_name", "Zebra Agent")
    if not isinstance(author_name, str) or not author_name.strip():
        return bad_request("author_name must be a non-blank string when provided")

    author_email = payload.get("author_email", "zebra-agent@example.local")
    if not isinstance(author_email, str) or not author_email.strip() or "@" not in author_email:
        return bad_request("author_email must be a valid email when provided")

    return {
        "message": message.strip(),
        "author_name": author_name.strip(),
        "author_email": author_email.strip(),
    }


def parse_pull_request_payload(
    payload: dict[str, object],
) -> PullRequestPayload | ApiResponse:
    title = payload.get("title")
    if not isinstance(title, str) or not title.strip():
        return bad_request("title must be a non-blank string")

    body = payload.get("body", "")
    if not isinstance(body, str):
        return bad_request("body must be a string when provided")

    base_branch = payload.get("base_branch", "main")
    if not isinstance(base_branch, str) or not base_branch.strip():
        return bad_request("base_branch must be a non-blank string when provided")

    head_branch = payload.get("head_branch")
    if head_branch is not None and (not isinstance(head_branch, str) or not head_branch.strip()):
        return bad_request("head_branch must be a non-blank string when provided")

    dry_run = payload.get("dry_run", True)
    if not isinstance(dry_run, bool):
        return bad_request("dry_run must be a boolean when provided")

    return {
        "title": title.strip(),
        "body": body.strip(),
        "base_branch": base_branch.strip(),
        "head_branch": head_branch.strip() if isinstance(head_branch, str) else None,
        "dry_run": dry_run,
    }


def parse_memory_overview_payload(
    payload: dict[str, object],
) -> MemoryOverviewPayload | ApiResponse:
    user_id = payload.get("user_id")
    if user_id is not None and (not isinstance(user_id, str) or not user_id.strip()):
        return bad_request("user_id must be a non-blank string when provided")

    tenant_id = payload.get("tenant_id")
    if tenant_id is not None and (not isinstance(tenant_id, str) or not tenant_id.strip()):
        return bad_request("tenant_id must be a non-blank string when provided")

    as_of = payload.get("as_of")
    parsed_as_of: datetime | None = None
    if as_of is not None:
        if not isinstance(as_of, str) or not as_of.strip():
            return bad_request("as_of must be a non-blank ISO 8601 string when provided")
        try:
            parsed_as_of = datetime.fromisoformat(as_of.strip())
        except ValueError:
            return bad_request("as_of must be a valid ISO 8601 datetime when provided")
        if parsed_as_of.tzinfo is None:
            return bad_request("as_of must include timezone information")
        parsed_as_of = parsed_as_of.astimezone(UTC)

    return {
        "user_id": user_id.strip() if isinstance(user_id, str) else None,
        "tenant_id": tenant_id.strip() if isinstance(tenant_id, str) else None,
        "as_of": parsed_as_of,
    }


def parse_queue_sweep_preview_payload(
    payload: dict[str, object],
) -> QueueSweepPreviewPayload | ApiResponse:
    decision = payload.get("decision")
    if decision not in {"confirm", "expire"}:
        return bad_request("decision must be either 'confirm' or 'expire'")

    memory_type = payload.get("memory_type")
    if memory_type is not None:
        if not isinstance(memory_type, str) or not memory_type.strip():
            return bad_request("memory_type must be a non-blank string when provided")
        try:
            MemoryType(memory_type.strip())
        except ValueError:
            return bad_request("memory_type is not supported")
        memory_type = memory_type.strip()

    return {
        "decision": decision,
        "memory_type": memory_type,
    }
