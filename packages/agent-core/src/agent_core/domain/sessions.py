from datetime import UTC, datetime
from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field

from agent_core.domain.clarifications import ClarificationContext
from agent_core.domain.identifiers import SessionId, new_session_id
from agent_core.domain.plans import SessionPlan


class SessionStatus(StrEnum):
    CREATED = "created"
    READY = "ready"
    RUNNING = "running"
    WAITING_APPROVAL = "waiting_approval"
    WAITING_INPUT = "waiting_input"
    SUSPENDED = "suspended"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


class ApprovalContext(BaseModel):
    model_config = ConfigDict(frozen=True)

    tool_name: str
    reason: str
    policy_profile: str
    route: str | None = None
    target: str | None = None
    network_profile: str | None = None
    scope: tuple[str, ...] = ()
    tool_call_id: str | None = None
    provider_call_id: str | None = None
    provider_tool_name: str | None = None
    provider_arguments: dict[str, object] = Field(default_factory=dict)
    arguments: dict[str, object] = Field(default_factory=dict)
    assistant_message: str | None = None
    call_fingerprint: str | None = None

    def to_mapping(self) -> dict[str, object]:
        mapping: dict[str, object] = {
            "tool_name": self.tool_name,
            "reason": self.reason,
            "policy_profile": self.policy_profile,
        }
        if self.route is not None:
            mapping["route"] = self.route
        if self.target is not None:
            mapping["target"] = self.target
        if self.network_profile is not None:
            mapping["network_profile"] = self.network_profile
        if self.scope:
            mapping["scope"] = list(self.scope)
        for field in (
            "tool_call_id",
            "provider_call_id",
            "provider_tool_name",
            "assistant_message",
            "call_fingerprint",
        ):
            value = getattr(self, field)
            if value is not None:
                mapping[field] = value
        if self.provider_arguments or self.provider_tool_name is not None:
            mapping["provider_arguments"] = self.provider_arguments
        if self.arguments or self.tool_call_id is not None:
            mapping["arguments"] = self.arguments
        return mapping


_ALLOWED_TRANSITIONS: dict[SessionStatus, set[SessionStatus]] = {
    SessionStatus.CREATED: {SessionStatus.READY, SessionStatus.CANCELLED},
    SessionStatus.READY: {
        SessionStatus.RUNNING,
        SessionStatus.SUSPENDED,
        SessionStatus.CANCELLED,
    },
    SessionStatus.RUNNING: {
        SessionStatus.WAITING_APPROVAL,
        SessionStatus.WAITING_INPUT,
        SessionStatus.SUSPENDED,
        SessionStatus.COMPLETED,
        SessionStatus.FAILED,
        SessionStatus.CANCELLED,
    },
    SessionStatus.WAITING_APPROVAL: {
        SessionStatus.RUNNING,
        SessionStatus.FAILED,
        SessionStatus.CANCELLED,
    },
    SessionStatus.WAITING_INPUT: {
        SessionStatus.READY,
        SessionStatus.FAILED,
        SessionStatus.CANCELLED,
    },
    SessionStatus.SUSPENDED: {SessionStatus.READY, SessionStatus.CANCELLED},
    SessionStatus.COMPLETED: set(),
    SessionStatus.FAILED: set(),
    SessionStatus.CANCELLED: set(),
}


class Session(BaseModel):
    model_config = ConfigDict(frozen=True)

    session_id: SessionId
    title: str
    status: SessionStatus
    created_at: datetime
    updated_at: datetime
    current_sequence: int = Field(default=0, ge=0)
    approval_context: ApprovalContext | None = None
    clarification_context: ClarificationContext | None = None
    task_plan: SessionPlan = Field(default_factory=SessionPlan)

    @classmethod
    def create(
        cls,
        *,
        title: str,
        created_at: datetime | None = None,
        session_id: SessionId | None = None,
    ) -> "Session":
        now = created_at or datetime.now(UTC)
        return cls(
            session_id=session_id or new_session_id(),
            title=title,
            status=SessionStatus.CREATED,
            created_at=now,
            updated_at=now,
            current_sequence=0,
        )

    def can_transition_to(self, next_status: SessionStatus) -> bool:
        return next_status in _ALLOWED_TRANSITIONS[self.status]

    def transition_to(
        self,
        next_status: SessionStatus,
        *,
        updated_at: datetime | None = None,
    ) -> "Session":
        if not self.can_transition_to(next_status):
            msg = f"invalid session transition: {self.status} -> {next_status}"
            raise ValueError(msg)

        return self.model_copy(
            update={
                "status": next_status,
                "updated_at": updated_at or datetime.now(UTC),
            }
        )

    def advance_sequence(self) -> "Session":
        return self.model_copy(update={"current_sequence": self.current_sequence + 1})
