"""Route-level Agent actions and their Host Grant scope requirements.

Each AgentAction names the stable Zebra capability vocabulary from ADR-017;
Hosts keep their own Grant scope wording and map onto these actions. The
legacy blanket ``agent.run`` scope stays accepted for unrecognised routes
until the versioned v1 API lands (AL-QUERY-API-V1-01).
"""

from __future__ import annotations

import re
from enum import StrEnum

LEGACY_RUN_SCOPE = "agent.run"


class AgentAction(StrEnum):
    """Stable Zebra-side action vocabulary; one action per route verb."""

    CREATE_TASK = "agent.task.create"
    SUBMIT_COMMAND = "agent.task.command"
    READ_TASK = "agent.task.read"
    READ_EVENTS = "agent.event.read"
    READ_ARTIFACT = "agent.artifact.read"
    DECIDE_APPROVAL = "agent.approval.decide"
    RESPOND_CLARIFICATION = "agent.clarification.respond"
    READ_USAGE = "agent.usage.read"


_TASK_PATTERN = re.compile(r"^/v1/tasks/(?P<task_id>[^/]+)$")
_TASK_COMMANDS_PATTERN = re.compile(r"^/v1/tasks/(?P<task_id>[^/]+)/commands$")
_TASK_EVENTS_PATTERN = re.compile(r"^/v1/tasks/(?P<task_id>[^/]+)/events$")
_ARTIFACT_PATTERN = re.compile(r"^/v1/artifacts/(?P<artifact_id>[^/]+)$")
_APPROVAL_DECISION_PATTERN = re.compile(r"^/v1/approvals/(?P<approval_id>[^/]+)/decisions$")
_CLARIFICATION_PATTERN = re.compile(r"^/v1/clarifications/(?P<id>[^/]+)/responses$")


def route_action(method: str, path: str) -> AgentAction | None:
    """Resolve the AgentAction for a canonical v1 route.

    Returns ``None`` for routes outside the versioned API surface; callers
    keep their existing authority behaviour for those paths.
    """

    verb = method.upper()
    if verb == "POST" and path == "/v1/tasks":
        return AgentAction.CREATE_TASK
    if verb == "POST" and _TASK_COMMANDS_PATTERN.match(path):
        return AgentAction.SUBMIT_COMMAND
    if verb == "GET" and _TASK_PATTERN.match(path):
        return AgentAction.READ_TASK
    if verb == "GET" and _TASK_EVENTS_PATTERN.match(path):
        return AgentAction.READ_EVENTS
    if verb == "GET" and _ARTIFACT_PATTERN.match(path):
        return AgentAction.READ_ARTIFACT
    if verb == "POST" and _APPROVAL_DECISION_PATTERN.match(path):
        return AgentAction.DECIDE_APPROVAL
    if verb == "POST" and _CLARIFICATION_PATTERN.match(path):
        return AgentAction.RESPOND_CLARIFICATION
    if verb == "GET" and path == "/v1/usage":
        return AgentAction.READ_USAGE
    return None


def action_scopes(action: AgentAction) -> frozenset[str]:
    """Grant scopes that authorise an action; one scope per action in v1."""

    return frozenset({action.value, LEGACY_RUN_SCOPE})
