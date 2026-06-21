from dataclasses import dataclass

from agent_core.application.session_projection import apply_event, rebuild_session
from agent_core.domain.identifiers import SessionId
from agent_core.domain.sessions import Session
from agent_core.ports.event_store import EventStorePort
from agent_core.ports.projection_store import ProjectionStorePort


class SessionRecoveryError(ValueError):
    """Raised when a worker cannot recover a durable session."""


@dataclass(frozen=True)
class RecoveredSession:
    session: Session
    event_count: int
    last_sequence: int
    is_terminal: bool


class SessionRecoveryService:
    def __init__(
        self,
        event_store: EventStorePort,
        projection_store: ProjectionStorePort,
    ) -> None:
        self._event_store = event_store
        self._projection_store = projection_store

    def recover_session(self, session_id: SessionId) -> RecoveredSession:
        projected_session = self._projection_store.get_session(session_id)
        if projected_session is not None:
            delta_events = self._event_store.read_since(
                session_id,
                projected_session.current_sequence,
            )
            session = projected_session
            for event in delta_events:
                session = apply_event(session, event)
            self._projection_store.save_session(session)
            return RecoveredSession(
                session=session,
                event_count=session.current_sequence + 1,
                last_sequence=session.current_sequence,
                is_terminal=session.status.value in {"completed", "failed", "cancelled"},
            )

        events = self._event_store.list_for_session(session_id)
        if not events:
            raise SessionRecoveryError("cannot recover missing session")

        session = rebuild_session(events)
        self._projection_store.save_session(session)
        return RecoveredSession(
            session=session,
            event_count=len(events),
            last_sequence=events[-1].sequence,
            is_terminal=session.status.value in {"completed", "failed", "cancelled"},
        )
