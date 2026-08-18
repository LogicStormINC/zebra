from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from agent_core.application.session_projection import apply_event
from agent_core.domain.agent_definition_snapshots import AgentDefinitionSnapshot
from agent_core.domain.events import EventActor, EventType, SessionEvent
from agent_core.domain.host_authority import HostContextEnvelope
from agent_core.domain.mcp import normalize_mcp_allowlist
from agent_core.domain.session_history import normalize_history_session_ids
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
    mcp_allowlist: tuple[str, ...] = ()
    skill_components: tuple[str, ...] = ()
    history_session_ids: tuple[str, ...] | None = None
    max_attempts: int = 1
    max_model_calls: int | None = None
    max_tool_calls: int | None = None
    host_context: HostContextEnvelope | None = None
    definition_snapshot: AgentDefinitionSnapshot | None = None
    created_at: datetime | None = None


@dataclass(frozen=True)
class BootstrappedSession:
    session: Session
    events: tuple[SessionEvent, ...]


class SessionBootstrapService:
    def build(self, command: SessionBootstrapCommand) -> BootstrappedSession:
        mcp_allowlist = normalize_mcp_allowlist(command.mcp_allowlist)
        history_session_ids = (
            None
            if command.history_session_ids is None
            else normalize_history_session_ids(command.history_session_ids)
        )
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
                    "mcp_allowlist": list(mcp_allowlist),
                    "skill_components": list(command.skill_components),
                    **(
                        {"history_session_ids": list(history_session_ids)}
                        if history_session_ids is not None
                        else {}
                    ),
                    "max_attempts": command.max_attempts,
                    "max_model_calls": command.max_model_calls,
                    "max_tool_calls": command.max_tool_calls,
                    **(
                        {
                            "host_context": command.host_context.model_dump(
                                mode="json", exclude_none=True
                            )
                        }
                        if command.host_context is not None
                        else {}
                    ),
                    **(
                        {
                            "definition_snapshot": command.definition_snapshot.model_dump(
                                mode="json", exclude_none=True
                            )
                        }
                        if command.definition_snapshot is not None
                        else {}
                    ),
                },
                created_at=session.created_at,
            ),
        )
        projected = session
        for event in events:
            projected = apply_event(projected, event)
        return BootstrappedSession(session=projected, events=events)
