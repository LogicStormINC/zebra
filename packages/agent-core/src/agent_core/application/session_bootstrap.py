from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from agent_core.application.session_projection import apply_event
from agent_core.domain.events import EventActor, EventType, SessionEvent
from agent_core.domain.sessions import Session
from agent_core.domain.tool_profiles import ToolProfile


@dataclass(frozen=True)
class SessionBootstrapCommand:
    title: str
    user_input: str
    workspace_root: Path
    policy_profile: str | None = None
    tool_profile: ToolProfile = ToolProfile.GENERAL
    network_profile: str = "none"
    network_allowlist: tuple[str, ...] = ()
    max_attempts: int = 1
    max_model_calls: int | None = 4
    max_tool_calls: int | None = 3
    created_at: datetime | None = None


@dataclass(frozen=True)
class BootstrappedSession:
    session: Session
    events: tuple[SessionEvent, ...]


class SessionBootstrapService:
    def build(self, command: SessionBootstrapCommand) -> BootstrappedSession:
        session = Session.create(title=command.title, created_at=command.created_at)
        events = (
            SessionEvent.create(
                session_id=session.session_id,
                sequence=0,
                event_type=EventType.SESSION_CREATED,
                actor=EventActor.USER,
                payload={"title": command.title},
                created_at=session.created_at,
            ),
            SessionEvent.create(
                session_id=session.session_id,
                sequence=1,
                event_type=EventType.USER_MESSAGE_RECEIVED,
                actor=EventActor.USER,
                payload={"content": command.user_input},
                created_at=session.created_at,
            ),
            SessionEvent.create(
                session_id=session.session_id,
                sequence=2,
                event_type=EventType.TASK_PREPARED,
                actor=EventActor.HARNESS,
                payload={
                    "title": command.title,
                    "user_input": command.user_input,
                    "workspace_root": str(command.workspace_root),
                    "policy_profile": command.policy_profile,
                    "tool_profile": command.tool_profile.value,
                    "network_profile": command.network_profile,
                    "network_allowlist": list(command.network_allowlist),
                    "max_attempts": command.max_attempts,
                    "max_model_calls": command.max_model_calls,
                    "max_tool_calls": command.max_tool_calls,
                },
                created_at=session.created_at,
            ),
        )
        projected = session
        for event in events:
            projected = apply_event(projected, event)
        return BootstrappedSession(session=projected, events=events)
