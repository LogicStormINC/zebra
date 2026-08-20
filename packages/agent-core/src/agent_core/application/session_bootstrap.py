from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from agent_core.application.session_projection import apply_event
from agent_core.domain.agent_definitions import AgentDefinition
from agent_core.domain.attempt_policy import TaskAttemptPolicy
from agent_core.domain.events import EventActor, EventType, SessionEvent
from agent_core.domain.identifiers import SessionId
from agent_core.domain.mcp import normalize_mcp_allowlist
from agent_core.domain.session_history import normalize_history_session_ids
from agent_core.domain.sessions import Session
from agent_core.domain.skills import (
    SkillComponentIdentity,
    normalize_skill_component_identities,
    normalize_skill_components,
)
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
    skill_component_identities: tuple[SkillComponentIdentity, ...] | None = None
    agent_definition: AgentDefinition | None = None
    history_session_ids: tuple[str, ...] | None = None
    max_attempts: int = 1
    max_corrections_per_attempt: int = 0
    execution_profile_id: str | None = None
    retryable_stop_reasons: tuple[str, ...] | None = None
    max_model_calls: int | None = None
    max_tool_calls: int | None = None
    plan_required: bool = False
    created_at: datetime | None = None
    session_id: SessionId | None = None
    model_id: str | None = None
    goal_binding: str = "conversational"
    goal_text: str | None = None
    goal_source: str | None = None

    def __post_init__(self) -> None:
        TaskAttemptPolicy(
            max_attempts=self.max_attempts,
            max_corrections_per_attempt=self.max_corrections_per_attempt,
            execution_profile_id=self.execution_profile_id,
            retryable_stop_reasons=(
                self.retryable_stop_reasons
                if self.retryable_stop_reasons is not None
                else TaskAttemptPolicy().retryable_stop_reasons
            ),
        )


@dataclass(frozen=True)
class BootstrappedSession:
    session: Session
    events: tuple[SessionEvent, ...]


class SessionBootstrapService:
    def build(self, command: SessionBootstrapCommand) -> BootstrappedSession:
        if not isinstance(command.plan_required, bool):
            raise ValueError("plan_required must be boolean")
        if command.goal_binding not in {"conversational", "goal_bound"}:
            raise ValueError("goal_binding must be 'conversational' or 'goal_bound'")
        if command.goal_binding == "goal_bound" and not (command.goal_text or "").strip():
            raise ValueError("goal_text must be provided for goal-bound tasks")
        mcp_allowlist = normalize_mcp_allowlist(command.mcp_allowlist)
        preapproved_readonly_tools = normalize_mcp_allowlist(command.preapproved_readonly_tools)
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
        skill_components = normalize_skill_components(command.skill_components)
        skill_component_identities = (
            None
            if command.skill_component_identities is None
            else normalize_skill_component_identities(command.skill_component_identities)
        )
        if skill_component_identities is not None and skill_components != tuple(
            identity.name for identity in skill_component_identities
        ):
            raise ValueError("skill component identities must match skill_components")
        session = Session.create(
            title=command.title,
            created_at=command.created_at,
            session_id=command.session_id,
        )
        goal_events = ()
        if command.goal_binding == "goal_bound":
            goal_events = (
                SessionEvent.create(
                    session_id=session.session_id,
                    sequence=1,
                    event_type=EventType.TASK_GOAL_SET,
                    actor=EventActor.HARNESS,
                    payload={
                        "binding": "goal_bound",
                        "goal_text": (command.goal_text or "").strip(),
                        "version": 1,
                        "source": command.goal_source or "task_bootstrap",
                        "stable_task_id": str(session.session_id),
                    },
                    created_at=session.created_at,
                ),
            )
            user_sequence_offset = 2
        else:
            user_sequence_offset = 1
        events = (
            SessionEvent.create(
                session_id=session.session_id,
                sequence=0,
                event_type=EventType.SESSION_CREATED,
                actor=EventActor.USER,
                payload={"title": command.title},
                created_at=session.created_at,
            ),
            *goal_events,
            SessionEvent.create(
                session_id=session.session_id,
                sequence=user_sequence_offset,
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
                sequence=user_sequence_offset + 1,
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
                    "skill_components": list(skill_components),
                    **(
                        {
                            "skill_component_identities": [
                                identity.model_dump(mode="json")
                                for identity in skill_component_identities
                            ]
                        }
                        if skill_component_identities is not None
                        else {}
                    ),
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
                    "max_corrections_per_attempt": command.max_corrections_per_attempt,
                    **(
                        {"execution_profile_id": command.execution_profile_id}
                        if command.execution_profile_id is not None
                        else {}
                    ),
                    "retryable_stop_reasons": list(
                        command.retryable_stop_reasons
                        if command.retryable_stop_reasons is not None
                        else TaskAttemptPolicy().retryable_stop_reasons
                    ),
                    "max_model_calls": command.max_model_calls,
                    "max_tool_calls": command.max_tool_calls,
                    **({"plan_required": True} if command.plan_required else {}),
                    **({"model_id": command.model_id} if command.model_id is not None else {}),
                    "goal_binding": command.goal_binding,
                    **(
                        {"goal_text": (command.goal_text or "").strip()}
                        if command.goal_binding == "goal_bound"
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
