from datetime import UTC, datetime
from pathlib import Path

from agent_core.application import SessionBootstrapCommand, SessionBootstrapService
from agent_core.domain.context_capsule import ContextCapsule
from agent_core.domain.events import EventActor, EventType
from agent_core.harness.context_window import ContextWindowExceededError, ContextWindowPlan
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
from zebra_agent_worker.execution_errors import error_metadata, exception_attempt_result
from zebra_agent_worker.execution_events import DurableHarnessEventRecorder
from zebra_agent_worker.model_call_index import ModelCallIndexer
from zebra_agent_worker.recovery import SessionRecoveryService
from zebra_agent_worker.tool_run_index import ToolRunIndexer

NOW = datetime(2026, 7, 17, 12, 0, tzinfo=UTC)


def test_context_window_overflow_is_a_recoverable_suspension() -> None:
    error = ContextWindowExceededError(
        ContextWindowPlan(
            estimated_input_tokens=420,
            input_token_limit=300,
            within_budget=False,
            compact_at=250,
            profile_name="tiny",
            estimate_method="chars_div_4",
            token_breakdown={"system": 20, "messages": 350, "tools": 50},
            attempted_strategies=("projection", "strict_original_history_retry"),
        )
    )

    result = exception_attempt_result(error, error_metadata(error, None, None))

    assert result.outcome.value == "suspended"
    assert result.metadata["stop_reason"] == "context_window_exceeded"
    assert result.metadata["estimated_input_tokens"] == 420
    assert result.metadata["input_token_limit"] == 300
    assert result.metadata["attempted_strategies"] == [
        "projection",
        "strict_original_history_retry",
    ]


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
    active = SQLiteContextLifecycleStore(database).get_active_capsule(bootstrap.session.session_id)
    assert active is not None
    assert active.capsule.source_event_range is not None
    assert recorder.session.current_sequence == events[-1].sequence


def test_compaction_includes_recent_exact_tail_refs_in_readability_check(
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
        capsule_id="temporary-tail",
        objective="Keep the acceptance criteria.",
        constraints=("Keep the acceptance criteria.",),
        immediate_next="Continue implementation.",
        source_hash="b" * 64,
        confidence=1.0,
        created_at=NOW,
        recent_exact_tail_refs=("event://session/1",),
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
    active = SQLiteContextLifecycleStore(database).get_active_capsule(bootstrap.session.session_id)
    assert active is not None
    assert active.capsule.recent_exact_tail_refs == ("event://session/1",)


def test_compaction_validation_failure_degrades_instead_of_raising(tmp_path: Path) -> None:
    """CTX-ART-01: a capsule that fails validation must not terminate the session.

    The worker records a non-terminal ``CONTEXT_COMPACTION_REJECTED`` diagnostic,
    preserves the existing active projection, and returns normally so the Agent
    can continue with the in-memory compacted conversation.
    """
    database = tmp_path / "context-fallback.sqlite"
    bootstrap = SessionBootstrapService().build(
        SessionBootstrapCommand(
            title="Fallback test",
            user_input="Keep going despite validation failure.",
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
    lifecycle_store = SQLiteContextLifecycleStore(database)
    # A capsule referencing a non-existent file:// artifact will fail the
    # readability check in validation.
    capsule = ContextCapsule(
        capsule_id="bad-ref",
        objective="Trigger validation failure",
        constraints=("Keep going.",),
        immediate_next="Continue",
        source_hash="0" * 64,
        confidence=1.0,
        created_at=NOW,
        artifact_refs=("file:///nonexistent/missing.txt",),
    )
    draft = HarnessEventDraft(
        event_type=EventType.CONTEXT_COMPACTED,
        actor=EventActor.HARNESS,
        payload={
            "attempt_number": 1,
            "before_tokens": 100,
            "after_tokens": 40,
            "removed_message_count": 2,
            "retained_message_count": 1,
            "within_budget": True,
            "provenance": "test",
            "capsule": capsule.model_dump(mode="json"),
        },
    )

    # Must not raise — the worker degrades gracefully.
    persist_context_compaction(
        draft,
        recorder=recorder,
        event_store=event_store,
        lifecycle_store=lifecycle_store,
    )

    events = event_store.list_for_session(bootstrap.session.session_id)
    event_types = [event.event_type for event in events]
    # The non-terminal diagnostic event is recorded instead of a terminal failure.
    assert EventType.CONTEXT_COMPACTION_REJECTED in event_types
    # No capsule was persisted — the active projection is preserved.
    assert EventType.CONTEXT_CAPSULE_CREATED not in event_types
    rejected = next(
        event for event in events if event.event_type is EventType.CONTEXT_COMPACTION_REJECTED
    )
    assert rejected.payload["fallback_mode"] == "retain_active_projection"
    assert rejected.payload["preserved_active_projection"] is True
