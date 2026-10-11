"""Exact resumable command/control state derived only from contiguous canonical Events."""

from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from agent_core.application.session_projection import apply_event, rebuild_session
from agent_core.application.task_turn_fields import SegmentTurnReadState
from agent_core.application.workspace_projection import apply_event as apply_workspace
from agent_core.application.workspace_projection import rebuild_workspace
from agent_core.domain.events import EventType, SessionEvent
from agent_core.domain.sessions import Session
from agent_core.domain.workspaces import WorkspaceProjection


class SessionCommandReadState(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    through_sequence: int = Field(default=-1, ge=-1, strict=True)
    last_event_id: UUID | None = None
    session: Session | None = None
    workspace: WorkspaceProjection | None = None
    turns: SegmentTurnReadState = Field(default_factory=SegmentTurnReadState)
    terminal_event_id: UUID | None = None
    resolved_event_id: UUID | None = None

    def advance(self, event: SessionEvent) -> "SessionCommandReadState":
        if event.sequence != self.through_sequence + 1 or (
            self.session is not None and event.session_id != self.session.session_id
        ):
            raise ValueError("command read state skips canonical revisions or crosses Session")
        session = (
            rebuild_session([event]) if self.session is None else apply_event(self.session, event)
        )
        workspace = self.workspace
        if workspace is not None:
            workspace = apply_workspace(workspace, event)
        elif event.event_type is EventType.TASK_PREPARED:
            workspace = rebuild_workspace([event])
        return self.model_copy(
            update={
                "through_sequence": event.sequence,
                "last_event_id": event.event_id,
                "session": session,
                "workspace": workspace,
                "turns": self.turns.advance(event),
                "terminal_event_id": event.event_id
                if event.event_type
                in {
                    EventType.SESSION_COMPLETED,
                    EventType.SESSION_FAILED,
                    EventType.SESSION_CANCELLED,
                }
                else self.terminal_event_id,
                "resolved_event_id": event.event_id
                if event.event_type is EventType.EXECUTION_AUTHORITY_RESOLVED
                else self.resolved_event_id,
            }
        )
