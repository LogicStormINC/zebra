"""Real durable Pages/checkpoints reconstruct frames without history hydration."""

from dataclasses import replace

import pytest
from agent_core.domain.sessions import Session
from agent_core.ports.task_projection_checkpoints import ProjectionScope
from agent_integrations.ag_ui.checkpoint_materializer import AgUiCheckpointMaterializer
from agent_integrations.ag_ui.checkpoint_plan import (
    AG_UI_CHECKPOINT_VERSION,
    ProjectionEventPlan,
    ProjectionPagePlan,
)
from agent_integrations.ag_ui.contracts import AgUiRunIdentity
from agent_integrations.ag_ui.task_stream import AgUiTaskProjector
from agent_storage import SQLiteAgentTaskStore, SQLiteEventStore, SQLiteProjectionStore

from tests.agent_integrations.test_ag_ui_projection import _golden_events


@pytest.mark.parametrize("chunk", [1, 2, 256])
def test_durable_exact_frame_restore_survives_store_reconstruction(tmp_path, chunk):
    database = tmp_path / "replay.sqlite"
    session = Session.create(title="Checkpoint replay")
    sources = _golden_events(session.session_id)
    event_store = SQLiteEventStore(database)
    for source in sources:
        event_store.append(source)
    SQLiteProjectionStore(database).save_session(
        session.model_copy(update={"current_sequence": len(sources) - 1})
    )
    store = SQLiteAgentTaskStore(database)
    task = store.ensure_for_session(session.session_id)
    while not store.backfill_replay_headers(task.task_id):
        pass  # Explicit legacy adoption, never a read-side repair.
    identity = AgUiRunIdentity(
        session_id=session.session_id, thread_id=str(task.task_id), run_id="legacy"
    )
    run = store.read_run_header(task.task_id, identity.run_id)
    scope = ProjectionScope("local", task.task_id, None, AG_UI_CHECKPOINT_VERSION)
    projector = AgUiCheckpointMaterializer(store)
    after = -1
    expected_source = []
    while after < run.highwater:
        page = store.read_event_page(task.task_id, after, limit=chunk)
        expected_source.extend(page.events)  # Test oracle only, never the restore path.
        plan = ProjectionPagePlan(
            run,
            tuple(
                ProjectionEventPlan(
                    store.read_event_header(task.task_id, item.task_sequence), True, True
                )
                for item in page.events
            ),
        )
        transition = projector.prepare_page(page, plan, scope, identity)
        assert transition is not None
        store.commit_projection_page(transition)
        after = page.next_sequence
    expected = list(AgUiTaskProjector().project_task_events(expected_source, identity))

    # No process memory survives. Every observation has one bounded body and
    # exact state keys; neither adapter nor projector may fall back to read_events.
    restored = SQLiteAgentTaskStore(database)

    def forbid_history(*_):
        raise AssertionError("restore attempted full Task hydration")

    restored.read_events = forbid_history
    actual = []
    materializer = AgUiCheckpointMaterializer(restored)
    for position in range(run.highwater + 1):
        entry = restored.read_event_page(task.task_id, position - 1, limit=1).events[0]
        actual.extend(materializer.iter_event_frames(scope, entry, identity, run=run))
    assert actual == expected
    for cursor, _ in expected:
        entry = restored.read_event_page(task.task_id, cursor.sequence - 1, limit=1).events[0]
        suffix = list(materializer.iter_event_frames(scope, entry, identity, run=run, after=cursor))
        assert suffix == [
            frame
            for frame in expected
            if frame[0].sequence == cursor.sequence and frame[0].frame_index > cursor.frame_index
        ]
    assert restored.read_checkpoint_head(scope).terminal.task_sequence == run.highwater
    with pytest.raises(ValueError, match="run"):
        materializer.restore_event_frames(
            replace(scope, anchor_event_id=sources[0].event_id), entry, identity, run=run
        )
