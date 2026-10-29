"""Actual SQLite and PostgreSQL cold observer restores the new standard producer."""

from agent_core.application.session_projection import rebuild_session
from agent_core.domain.events import EventType
from agent_core.domain.identifiers import TaskId
from agent_core.ports.task_projection_checkpoints import ProjectionScope
from agent_integrations.ag_ui.checkpoint_binding import build_projection_page_plan
from agent_integrations.ag_ui.checkpoint_materializer import AgUiCheckpointMaterializer
from agent_integrations.ag_ui.checkpoint_observer import AgUiCheckpointObserver
from agent_integrations.ag_ui.checkpoint_plan import checkpoint_version
from agent_integrations.ag_ui.contracts import AgUiRunIdentity
from agent_integrations.ag_ui.profiles import AgUiProjectionProfile
from agent_integrations.ag_ui.standard_projection import StandardAgUiProjector
from agent_integrations.ag_ui.standard_state import StandardProjectionState

from tests.agent_integrations import test_ag_ui_binding_persistence as persistence
from tests.agent_integrations.binding_store_cases import append, ready, resolve, root
from tests.agent_integrations.test_ag_ui_standard_projection import VALIDATOR

metadata_dsn = persistence.metadata_dsn
standard_stores = persistence.stores


def test_native_standard_profile_exact_cold_replay_and_root_cells(standard_stores):
    stores = standard_stores
    segment = root(stores)
    from uuid import uuid4

    from agent_core.contracts.session_commands import SessionCommand, SessionCommandKind

    append(
        stores, segment, 2, EventType.TASK_PREPARED, {"title": "standard", "user_input": "fixture"}
    )
    append(stores, segment, 3, EventType.HARNESS_ATTEMPT_STARTED, {"attempt_number": 1})
    append(
        stores,
        segment,
        4,
        EventType.MODEL_RESPONSE_RECEIVED,
        {"model_call_id": "m", "assistant_message": "PRIVATE", "input_tokens": 2},
    )
    append(
        stores,
        segment,
        5,
        EventType.ANSWER_COMMITTED,
        {
            "attempt_number": 1,
            "assistant_message": "public answer",
            "delivery_assessment": {"status": "complete"},
        },
    )
    append(
        stores, segment, 6, EventType.SESSION_SUSPENDED, {"reason": "execution_storage_unavailable"}
    )
    resume = SessionCommand(
        command_id=uuid4(),
        session_id=segment,
        kind=SessionCommandKind.RESUME,
        expected_revision=6,
        idempotency_key="approval-resume:standard-native",
        payload={},
    )
    append(stores, segment, 7, EventType.SESSION_COMMAND_ACCEPTED, resume.event_payload())
    append(stores, segment, 8, EventType.SESSION_RESUMED, {"reason": "approval_resolved"})
    append(stores, segment, 9, EventType.HARNESS_ATTEMPT_STARTED, {"attempt_number": 2})
    append(
        stores,
        segment,
        10,
        EventType.MODEL_RESPONSE_RECEIVED,
        {"model_call_id": "after", "input_tokens": 3},
    )
    append(stores, segment, 11, EventType.SESSION_CANCELLED, {"reason": "cancelled"})
    stores.sessions.save_session(rebuild_session(stores.events.list_for_session(segment)))
    task = TaskId(segment)
    run = ready(stores.tasks, task)
    profile = AgUiProjectionProfile(
        "agui-standard-1.0", projector=StandardAgUiProjector(), state_type=StandardProjectionState
    )
    scope = ProjectionScope(
        stores.namespace, task, run.anchor.event_id, checkpoint_version(run, profile)
    )
    identity = AgUiRunIdentity(session_id=segment, thread_id=str(task), run_id="run")
    continuation = stores.tasks.read_event_header(task, 7)
    assert continuation.internal_continuation and continuation.command_kind == "resume"
    assert continuation.command_run_id is None
    first = profile.protocol_run_id(stores.tasks, scope, run, run.anchor)
    second = profile.protocol_run_id(stores.tasks, scope, run, continuation)
    assert first != second
    resolve(stores.tasks, run, scope)
    materializer = AgUiCheckpointMaterializer(stores.tasks, profile=profile)
    page = stores.tasks.read_event_page(
        task, after_sequence=-1, limit=256, through_sequence=run.highwater
    )
    plan = build_projection_page_plan(stores.tasks, page, run, scope, identity, profile=profile)
    transition = materializer.prepare_page(page, plan, scope, identity)
    assert transition is not None
    stores.tasks.commit_projection_page(transition)
    observer = AgUiCheckpointObserver(stores.cold(), namespace=stores.namespace, profile=profile)
    snapshot = observer.snapshot(task, identity)
    cold_page = observer.read_page(snapshot, run.start - 1)
    frames = list(observer.iter_page_frames(snapshot, cold_page, identity))
    assert "PRIVATE" not in str(frames)
    assert [f.run_id for _, f in frames if f.type.value == "RUN_STARTED"] == [first, second]
    assert [
        f.usage[0].input_tokens for _, f in frames if f.type.value in {"RUN_FINISHED", "RUN_ERROR"}
    ] == [2, 3]
    assert any(f.type.value == "TEXT_MESSAGE_CONTENT" for _, f in frames)
    for cursor, frame in frames:
        VALIDATOR.validate(frame.model_dump(mode="json", by_alias=True, exclude_none=True))
        single = next(e for e in cold_page.events if e.task_sequence == cursor.sequence)
        assert list(
            observer.materializer.iter_event_frames(scope, single, identity, run=run, after=cursor)
        ) == [
            (c, f)
            for c, f in frames
            if c.sequence == cursor.sequence and c.frame_index > cursor.frame_index
        ]
