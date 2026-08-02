from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from agent_core.application.session_projection import apply_event
from agent_core.domain.agent_definitions import AgentDefinition
from agent_core.domain.events import EventActor, EventType, SessionEvent
from agent_core.domain.identifiers import SessionId
from agent_core.domain.mcp import normalize_mcp_allowlist
from agent_core.domain.session_history import normalize_history_session_ids
from agent_core.domain.sessions import Session
from agent_core.domain.tool_profiles import ToolProfile


@dataclass(frozen=True)
class SessionBootstrapCommand:
    title: str
    user_input: str
    workspace_root: Path
    public_content: str | None = None
    policy_profile: str | None = None
    tool_profile: ToolProfile = ToolProfile.GENERAL
    network_profile: str = "none"
    network_allowlist: tuple[str, ...] = ()
    mcp_allowlist: tuple[str, ...] = ()
    preapproved_readonly_tools: tuple[str, ...] = ()
    skill_components: tuple[str, ...] = ()
    agent_definition: AgentDefinition | None = None
    history_session_ids: tuple[str, ...] | None = None
    max_attempts: int = 1
    max_model_calls: int | None = None
    max_tool_calls: int | None = None
    created_at: datetime | None = None
    session_id: SessionId | None = None


@dataclass(frozen=True)
class BootstrappedSession:
    session: Session
    events: tuple[SessionEvent, ...]


class SessionBootstrapService:
    def build(self, command: SessionBootstrapCommand) -> BootstrappedSession:
        mcp_allowlist = normalize_mcp_allowlist(command.mcp_allowlist)
        preapproved_readonly_tools = normalize_mcp_allowlist(
            command.preapproved_readonly_tools
        )
        if preapproved_readonly_tools and (
            command.policy_profile != "read_only"
            or command.network_profile != "mcp-proxy-only"
            or not set(preapproved_readonly_tools) <= set(mcp_allowlist)
        ):
            raise ValueError("preapproved read-only tools require scoped Task authority")
        history_session_ids = (
            None
            if command.history_session_ids is None
            else normalize_history_session_ids(command.history_session_ids)
        )
        session = Session.create(
            title=command.title,
            created_at=command.created_at,
            session_id=command.session_id,
        )
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
                payload={
                    "content": command.user_input,
                    **(
                        {"public_content": command.public_content}
                        if command.public_content is not None
                        else {}
                    ),
                },
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
                    "preapproved_readonly_tools": list(preapproved_readonly_tools),
                    "skill_components": list(command.skill_components),
                    **(
                        {"agent_definition": command.agent_definition.model_dump(mode="json")}
                        if command.agent_definition is not None
                        else {}
                    ),
                    **(
                        {"history_session_ids": list(history_session_ids)}
                        if history_session_ids is not None
                        else {}
                    ),
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
