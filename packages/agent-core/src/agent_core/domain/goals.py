"""Wave 5 P3A-1: goal_binding for stable tasks.

A single visible conversation is one Zebra Stable Task. Each stable task
declares an explicit ``goal_binding`` of either ``conversational`` (no
durable Goal; the current Turn is the response focus) or ``goal_bound``
(durable, versioned ``Goal`` that follows the user across turns and
recovery boundaries).

Legacy recovery priority (W5-P3A-1):

1. explicit goal_binding
2. existing durable goal/plan/completion signal
3. legacy plan_required=true
4. otherwise conversational

The module never references FinOS Skill identifiers; Zebra runtime logic
must remain Skill-name free.
"""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field, field_validator


class GoalBinding(StrEnum):
    CONVERSATIONAL = "conversational"
    GOAL_BOUND = "goal_bound"


MAX_GOAL_TEXT_CHARS = 1_024


class Goal(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    binding: GoalBinding
    text: str = Field(min_length=1, max_length=MAX_GOAL_TEXT_CHARS)
    version: int = Field(ge=1)
    created_at: datetime

    @field_validator("text")
    @classmethod
    def normalize_text(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("goal text must not be blank")
        return normalized

    @field_validator("created_at")
    @classmethod
    def ensure_timezone(cls, value: datetime) -> datetime:
        if value.tzinfo is None:
            raise ValueError("goal created_at must be timezone-aware")
        return value


def resolve_goal_binding(
    *,
    explicit_binding: GoalBinding | None,
    existing_goal_text: str | None,
    plan_required: bool,
) -> tuple[GoalBinding, str | None]:
    """Resolve the active goal binding using the legacy recovery priority."""
    if explicit_binding is not None:
        return explicit_binding, existing_goal_text
    if existing_goal_text is not None and existing_goal_text.strip():
        return GoalBinding.GOAL_BOUND, existing_goal_text.strip()
    if plan_required:
        return GoalBinding.GOAL_BOUND, None
    return GoalBinding.CONVERSATIONAL, None


def set_session_goal(
    session: "Session",
    binding: GoalBinding,
    text: str,
    *,
    created_at: datetime,
) -> "Session":
    """Return a new Session with TASK_GOAL_SET applied at ``created_at``.

    The first Goal is always version 1. Existing durable goals are
    superseded if and only if the caller explicitly invokes
    :func:`revise_session_goal` (which increments the version).
    """
    from agent_core.domain.sessions import Session  # local import to avoid cycle

    if not isinstance(session, Session):
        raise TypeError("set_session_goal requires a Session instance")
    if not isinstance(binding, GoalBinding):
        raise ValueError("binding must be a GoalBinding enum value")
    if created_at.tzinfo is None:
        raise ValueError("created_at must be timezone-aware")
    if session.active_goal is not None and binding is GoalBinding.GOAL_BOUND:
        # Do not silently overwrite an existing goal; require revise_session_goal.
        return session
    goal = Goal(
        binding=binding,
        text=text,
        version=1,
        created_at=created_at,
    )
    return session.model_copy(
        update={
            "goal_binding": binding,
            "active_goal": goal if binding is GoalBinding.GOAL_BOUND else None,
            "updated_at": created_at,
        }
    )


def revise_session_goal(
    session: "Session",
    *,
    new_text: str,
    created_at: datetime,
) -> "Session":
    """Return a new Session with the Goal text revised and version + 1.

    A goal_bound session is required. Conversational sessions cannot
    carry a durable Goal across revisions.
    """
    from agent_core.domain.sessions import Session

    if not isinstance(session, Session):
        raise TypeError("revise_session_goal requires a Session instance")
    if created_at.tzinfo is None:
        raise ValueError("created_at must be timezone-aware")
    if session.goal_binding is not GoalBinding.GOAL_BOUND:
        raise ValueError(
            "revise_session_goal requires a goal_bound session; "
            f"got {session.goal_binding}"
        )
    next_version = 1 if session.active_goal is None else session.active_goal.version + 1
    goal = Goal(
        binding=GoalBinding.GOAL_BOUND,
        text=new_text,
        version=next_version,
        created_at=created_at,
    )
    return session.model_copy(
        update={
            "goal_binding": GoalBinding.GOAL_BOUND,
            "active_goal": goal,
            "updated_at": created_at,
        }
    )


def apply_goal_event(
    session: "Session",
    event: "SessionEvent",
) -> "Session":
    """Apply a TASK_GOAL_SET or TASK_GOAL_REVISED event to a session.

    Other event types are passed through unchanged. Old events are never
    mutated; the projection is read-only over the historical event log.
    """
    from agent_core.domain.events import EventType
    from agent_core.domain.sessions import Session

    if not isinstance(session, Session):
        raise TypeError("apply_goal_event requires a Session instance")
    if event.session_id != session.session_id:
        raise ValueError("event session_id does not match session")
    if event.event_type is EventType.TASK_GOAL_SET:
        binding_raw = event.payload.get("binding", "conversational")
        try:
            binding = GoalBinding(str(binding_raw))
        except ValueError as error:
            raise ValueError(
                f"TASK_GOAL_SET payload has invalid binding: {binding_raw!r}"
            ) from error
        goal_text = event.payload.get("goal_text")
        if binding is GoalBinding.GOAL_BOUND:
            if not isinstance(goal_text, str) or not goal_text.strip():
                raise ValueError("TASK_GOAL_SET goal_text must be a non-blank string")
            existing_version = (
                session.active_goal.version if session.active_goal is not None else 0
            )
            version = int(event.payload.get("version", existing_version + 1))
            if version < 1:
                raise ValueError("goal version must be >= 1")
            goal = Goal(
                binding=GoalBinding.GOAL_BOUND,
                text=goal_text.strip(),
                version=version,
                created_at=event.created_at,
            )
            return session.model_copy(
                update={
                    "goal_binding": GoalBinding.GOAL_BOUND,
                    "active_goal": goal,
                    "updated_at": event.created_at,
                    "current_sequence": event.sequence,
                }
            )
        return session.model_copy(
            update={
                "goal_binding": GoalBinding.CONVERSATIONAL,
                "active_goal": None,
                "updated_at": event.created_at,
                "current_sequence": event.sequence,
            }
        )
    if event.event_type is EventType.TASK_GOAL_REVISED:
        if session.goal_binding is not GoalBinding.GOAL_BOUND:
            raise ValueError(
                "TASK_GOAL_REVISED requires the session to be goal_bound"
            )
        goal_text = event.payload.get("goal_text")
        if not isinstance(goal_text, str) or not goal_text.strip():
            raise ValueError("TASK_GOAL_REVISED goal_text must be a non-blank string")
        version = int(event.payload.get("version", session.active_goal.version + 1 if session.active_goal else 1))
        goal = Goal(
            binding=GoalBinding.GOAL_BOUND,
            text=goal_text.strip(),
            version=version,
            created_at=event.created_at,
        )
        return session.model_copy(
            update={
                "active_goal": goal,
                "updated_at": event.created_at,
                "current_sequence": event.sequence,
            }
        )
    return session
