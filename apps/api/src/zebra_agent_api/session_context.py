from __future__ import annotations

from pathlib import Path

from agent_core.domain.events import EventType, SessionEvent


def session_workspace_root(events: list[SessionEvent]) -> Path | None:
    workspace_root: Path | None = None
    for event in events:
        if event.event_type is not EventType.TASK_PREPARED:
            continue
        raw_workspace_root = event.payload.get("workspace_root")
        if isinstance(raw_workspace_root, str) and raw_workspace_root.strip():
            workspace_root = Path(raw_workspace_root).expanduser().resolve()
    return workspace_root


def session_policy_profile(events: list[SessionEvent]) -> str | None:
    policy_profile: str | None = None
    for event in events:
        if event.event_type is not EventType.TASK_PREPARED:
            continue
        raw_policy_profile = event.payload.get("policy_profile")
        if isinstance(raw_policy_profile, str) and raw_policy_profile.strip():
            policy_profile = raw_policy_profile.strip()
    return policy_profile
