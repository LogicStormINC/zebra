from dataclasses import dataclass

from agent_core.application.session_projection import apply_event, rebuild_session
from agent_core.application.workspace_projection import (
    apply_event as apply_workspace_event,
)
from agent_core.application.workspace_projection import (
    rebuild_workspace,
)
from agent_core.domain.identifiers import SessionId
from agent_core.domain.sessions import Session
from agent_core.domain.workspaces import WorkspaceProjection
from agent_core.ports.event_store import EventStorePort
from agent_core.ports.projection_store import ProjectionStorePort
from agent_core.ports.workspace_projection_store import WorkspaceProjectionStorePort


class SessionRecoveryError(ValueError):
    """Raised when a worker cannot recover a durable session."""


@dataclass(frozen=True)
class RecoveredSession:
    session: Session
    workspace: WorkspaceProjection
    event_count: int
    last_sequence: int
    is_terminal: bool


class SessionRecoveryService:
    def __init__(
        self,
        event_store: EventStorePort,
        projection_store: ProjectionStorePort,
        workspace_store: WorkspaceProjectionStorePort | None = None,
    ) -> None:
        self._event_store = event_store
        self._projection_store = projection_store
        self._workspace_store = workspace_store

    def recover_session(self, session_id: SessionId) -> RecoveredSession:
        projected_session = self._projection_store.get_session(session_id)
        if projected_session is not None:
            delta_events = self._event_store.read_since(
                session_id,
                projected_session.current_sequence,
            )
            session = projected_session
            workspace = self._recover_workspace_projection(session_id)
            for event in delta_events:
                session = apply_event(session, event)
                workspace = apply_workspace_event(workspace, event)
            self._projection_store.save_session(session)
            if self._workspace_store is not None:
                self._workspace_store.save_workspace(workspace)
            return RecoveredSession(
                session=session,
                workspace=workspace,
                event_count=session.current_sequence + 1,
                last_sequence=session.current_sequence,
                is_terminal=session.status.value in {"completed", "failed", "cancelled"},
            )

        events = self._event_store.list_for_session(session_id)
        if not events:
            raise SessionRecoveryError("cannot recover missing session")

        session = rebuild_session(events)
        workspace = rebuild_workspace(events)
        self._projection_store.save_session(session)
        if self._workspace_store is not None:
            self._workspace_store.save_workspace(workspace)
        return RecoveredSession(
            session=session,
            workspace=workspace,
            event_count=len(events),
            last_sequence=events[-1].sequence,
            is_terminal=session.status.value in {"completed", "failed", "cancelled"},
        )

    def _recover_workspace_projection(self, session_id: SessionId) -> WorkspaceProjection:
        if self._workspace_store is not None:
            projected_workspace = self._workspace_store.get_workspace(session_id)
            if projected_workspace is not None:
                delta_events = self._event_store.read_since(
                    session_id,
                    projected_workspace.current_sequence,
                )
                workspace = projected_workspace
                for event in delta_events:
                    workspace = apply_workspace_event(workspace, event)
                return workspace

        events = self._event_store.list_for_session(session_id)
        if not events:
            raise SessionRecoveryError("cannot recover missing session")
        return rebuild_workspace(events)
