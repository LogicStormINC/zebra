from __future__ import annotations

from typing import TypedDict

from agent_security import PolicyProfile

from zebra_agent_api.responses import ApiResponse, bad_request


class CreateSessionPayload(TypedDict):
    prompt: str
    title: str
    workspace: str
    execute: bool
    policy_profile: str


class ResumeSessionPayload(TypedDict):
    worker_id: str
    lease_ttl_seconds: int


class AppendSessionMessagePayload(TypedDict):
    content: str


class ApprovalDecisionPayload(TypedDict):
    operator: str
    reason: str


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


def parse_create_session_payload(
    payload: dict[str, object],
) -> CreateSessionPayload | ApiResponse:
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

    return {
        "prompt": prompt.strip(),
        "title": title.strip(),
        "workspace": workspace.strip(),
        "execute": execute,
        "policy_profile": policy_profile,
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


def parse_append_session_message_payload(
    payload: dict[str, object],
) -> AppendSessionMessagePayload | ApiResponse:
    content = payload.get("content")
    if not isinstance(content, str) or not content.strip():
        return bad_request("content must be a non-blank string")
    return {"content": content.strip()}


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
