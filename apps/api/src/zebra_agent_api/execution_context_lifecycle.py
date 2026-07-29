from pathlib import Path

from agent_context.capsule import durable_context_capsule, durable_context_validation_context
from agent_core.application.session_projection import rebuild_session
from agent_core.application.workspace_projection import rebuild_workspace
from agent_core.domain.context_capsule import ContextCapsule, ContextCapsuleValidationError
from agent_core.domain.events import EventActor, EventType, SessionEvent
from agent_core.domain.sessions import Session
from agent_storage import (
    SQLiteContextLifecycleStore,
    SQLiteEventStore,
    SQLiteProjectionStore,
    SQLiteWorkspaceProjectionStore,
)


def persist_execution_events(
    database_path: Path,
    events: tuple[SessionEvent, ...],
) -> Session:
    """Persist synchronous harness events through the durable context boundary."""
    event_store = SQLiteEventStore(database_path)
    lifecycle = SQLiteContextLifecycleStore(database_path)
    persisted: list[SessionEvent] = []
    for original in events:
        event = original.model_copy(update={"sequence": len(persisted)})
        raw_capsule = event.payload.get("capsule")
        if event.event_type is not EventType.CONTEXT_COMPACTED or not isinstance(
            raw_capsule, dict
        ):
            event_store.append(event)
            persisted.append(event)
            continue
        capsule = durable_context_capsule(ContextCapsule.model_validate(raw_capsule), persisted)
        active = lifecycle.get_active_capsule(event.session_id)
        try:
            stored = lifecycle.persist_capsule_and_advance(
                session_id=event.session_id,
                capsule=capsule,
                validation_context=durable_context_validation_context(capsule),
                sequence=event.sequence,
                expected_active_capsule_id=active.capsule.capsule_id if active else None,
                compaction_event=event,
            )
        except ContextCapsuleValidationError as exc:
            rejected = SessionEvent.create(
                session_id=event.session_id,
                sequence=event.sequence,
                event_type=EventType.CONTEXT_COMPACTION_REJECTED,
                actor=EventActor.SYSTEM,
                created_at=event.created_at,
                payload={
                    "capsule_id": capsule.capsule_id,
                    "rejection_reason": str(exc),
                    "fallback_mode": "retain_active_projection",
                    "preserved_active_projection": True,
                },
            )
            event_store.append(rejected)
            persisted.append(rejected)
            continue
        persisted.extend((event, stored.event))
    session = rebuild_session(persisted)
    SQLiteProjectionStore(database_path).save_session(session)
    SQLiteWorkspaceProjectionStore(database_path).save_workspace(rebuild_workspace(persisted))
    return session
