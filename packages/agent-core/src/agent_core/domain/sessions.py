from datetime import UTC, datetime
from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field

from agent_core.domain.identifiers import SessionId, new_session_id


class SessionStatus(StrEnum):
    CREATED = "created"
    READY = "ready"
    RUNNING = "running"
    WAITING_APPROVAL = "waiting_approval"
    SUSPENDED = "suspended"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


_ALLOWED_TRANSITIONS: dict[SessionStatus, set[SessionStatus]] = {
    SessionStatus.CREATED: {SessionStatus.READY, SessionStatus.CANCELLED},
    SessionStatus.READY: {SessionStatus.RUNNING, SessionStatus.CANCELLED},
    SessionStatus.RUNNING: {
        SessionStatus.WAITING_APPROVAL,
        SessionStatus.SUSPENDED,
        SessionStatus.COMPLETED,
        SessionStatus.FAILED,
        SessionStatus.CANCELLED,
    },
    SessionStatus.WAITING_APPROVAL: {SessionStatus.RUNNING, SessionStatus.CANCELLED},
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

    @classmethod
    def create(cls, *, title: str, created_at: datetime | None = None) -> "Session":
        now = created_at or datetime.now(UTC)
        return cls(
            session_id=new_session_id(),
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
