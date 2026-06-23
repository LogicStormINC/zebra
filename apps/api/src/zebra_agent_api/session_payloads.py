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
