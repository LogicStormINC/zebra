from datetime import UTC, datetime
from pathlib import Path

from agent_core.application import SessionBootstrapCommand, SessionBootstrapService
from agent_core.domain.context_capsule import ContextCapsule
from agent_core.domain.events import EventActor, EventType
from agent_core.harness.models import HarnessEventDraft
from agent_storage import (
    SQLiteArtifactPayloadStore,
    SQLiteContextLifecycleStore,
    SQLiteEventStore,
    SQLiteModelCallStore,
    SQLiteProjectionStore,
    SQLiteToolRunStore,
    SQLiteWorkspaceProjectionStore,
)
from zebra_agent_worker.context_lifecycle import persist_context_compaction
from zebra_agent_worker.execution_events import DurableHarnessEventRecorder
from zebra_agent_worker.model_call_index import ModelCallIndexer
from zebra_agent_worker.recovery import SessionRecoveryService
from zebra_agent_worker.tool_run_index import ToolRunIndexer

NOW = datetime(2026, 7, 17, 12, 0, tzinfo=UTC)


def test_compaction_capsule_event_and_active_projection_commit_atomically(
    tmp_path: Path,
) -> None:
    database = tmp_path / "context.sqlite"
    bootstrap = SessionBootstrapService().build(
        SessionBootstrapCommand(
            title="Context lifecycle",
            user_input="Keep the acceptance criteria.",
            workspace_root=tmp_path.resolve(),
        )
    )
    event_store = SQLiteEventStore(database)
    for event in bootstrap.events:
        event_store.append(event)
    projection_store = SQLiteProjectionStore(database)
    projection_store.save_session(bootstrap.session)
    workspace_store = SQLiteWorkspaceProjectionStore(database)
    recovery = SessionRecoveryService(
        event_store, projection_store, workspace_store
    ).recover_session(bootstrap.session.session_id)
    payload_store = SQLiteArtifactPayloadStore(database)
    recorder = DurableHarnessEventRecorder(
        session=recovery.session,
        workspace=recovery.workspace,
        event_store=event_store,
        projection_store=projection_store,
        workspace_store=workspace_store,
        model_call_indexer=ModelCallIndexer(SQLiteModelCallStore(database)),
        tool_run_indexer=ToolRunIndexer(SQLiteToolRunStore(database), payload_store),
    )
    capsule = ContextCapsule(
        capsule_id="temporary",
        objective="Keep the acceptance criteria.",
        constraints=("Keep the acceptance criteria.",),
        immediate_next="Continue implementation.",
        source_hash="a" * 64,
        confidence=1.0,
        created_at=NOW,
    )
    draft = HarnessEventDraft(
        event_type=EventType.CONTEXT_COMPACTED,
        actor=EventActor.HARNESS,
        payload={
            "attempt_number": 1,
            "before_tokens": 100,
            "after_tokens": 40,
            "removed_message_count": 4,
            "retained_message_count": 2,
            "within_budget": True,
            "provenance": "test",
            "capsule": capsule.model_dump(mode="json"),
        },
    )

    persist_context_compaction(
        draft,
        recorder=recorder,
        event_store=event_store,
        lifecycle_store=SQLiteContextLifecycleStore(database),
    )

    events = event_store.list_for_session(bootstrap.session.session_id)
    assert [event.event_type for event in events[-2:]] == [
        EventType.CONTEXT_COMPACTED,
        EventType.CONTEXT_CAPSULE_CREATED,
    ]
    active = SQLiteContextLifecycleStore(database).get_active_capsule(
        bootstrap.session.session_id
    )
    assert active is not None
    assert active.capsule.source_event_range is not None
    assert recorder.session.current_sequence == events[-1].sequence
