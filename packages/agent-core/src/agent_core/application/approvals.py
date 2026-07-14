from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum

from agent_core.domain.events import EventActor, EventType, SessionEvent
from agent_core.domain.sessions import ApprovalContext, Session, SessionStatus


class ApprovalDecisionAction(StrEnum):
    GRANT = "grant"
    REJECT = "reject"


@dataclass(frozen=True)
class ApprovalDecisionCommand:
    action: ApprovalDecisionAction
    operator: str
    reason: str
    created_at: datetime | None = None

    def __post_init__(self) -> None:
        if not self.operator.strip():
            raise ValueError("approval decision operator must not be blank")
        if not self.reason.strip():
            raise ValueError("approval decision reason must not be blank")
        if self.created_at is not None and self.created_at.tzinfo is None:
            raise ValueError("approval decision created_at must be timezone-aware")


@dataclass(frozen=True)
class ApprovalDecisionService:
    def build_event(
        self,
        *,
        session: Session,
        next_sequence: int,
        command: ApprovalDecisionCommand,
    ) -> SessionEvent:
        if session.status is not SessionStatus.WAITING_APPROVAL:
            raise ValueError("approval decisions require a waiting approval session")
        if next_sequence != session.current_sequence + 1:
            raise ValueError("approval decision sequence must follow current session")
        event_type = (
            EventType.APPROVAL_GRANTED
            if command.action is ApprovalDecisionAction.GRANT
            else EventType.APPROVAL_REJECTED
        )
        return SessionEvent.create(
            session_id=session.session_id,
            sequence=next_sequence,
            event_type=event_type,
            actor=EventActor.USER,
            payload={
                "operator": command.operator.strip(),
                "reason": command.reason.strip(),
                **_approval_binding(session.approval_context),
            },
            created_at=command.created_at,
        )


def _approval_binding(context: ApprovalContext | None) -> dict[str, object]:
    if not isinstance(context, ApprovalContext):
        return {}
    return {
        key: value
        for key, value in {
            "tool_call_id": context.tool_call_id,
            "call_fingerprint": context.call_fingerprint,
        }.items()
        if value is not None
    }
