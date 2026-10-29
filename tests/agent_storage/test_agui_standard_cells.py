"""Independent standard state cannot bypass native Task/namespace/root validation."""

from dataclasses import replace
from uuid import uuid4

import pytest
from agent_core.ports.task_projection_checkpoints import (
    CheckpointConflict,
    ProjectionCell,
    ProjectionCellKey,
)

from tests.agent_storage.test_task_projection_checkpoints import _fixture, _transition


def test_standard_cells_are_root_bound_and_legacy_profile_cannot_restore(tmp_path):
    store, legacy, events = _fixture(tmp_path / "standard.sqlite")
    scope = replace(
        legacy, anchor_event_id=events[0].event_id, projector_version="agui-standard-1.0:r1"
    )
    key = ProjectionCellKey(events[0].session_id, "standard_v1", "count")
    cell = ProjectionCell(key, 0, "3")
    transition = _transition(scope, events, stop=1, cells=(cell,))
    store.commit_projection_page(transition)
    assert store.read_cells_at(scope, 1, (key,)) == (cell,)
    assert store.read_cells_at(legacy, 0, (key,)) == ()
    for invalid in [replace(scope, task_id=uuid4()), replace(scope, namespace="foreign")]:
        with pytest.raises(CheckpointConflict):
            store.read_cells_at(invalid, 1, (key,))
    with pytest.raises(ValueError, match="standard profile"):
        replace(transition, scope=legacy)
    for invalid in ("agui-standard-1.0:r1000", "agui-standard-1x0:r1"):
        with pytest.raises(ValueError, match="standard profile"):
            replace(transition, scope=replace(scope, projector_version=invalid))


def test_foreign_standard_root_is_rejected_before_atomic_commit(tmp_path):
    store, legacy, events = _fixture(tmp_path / "standard.sqlite")
    scope = replace(
        legacy, anchor_event_id=events[0].event_id, projector_version="agui-standard-1.0:r1"
    )
    cell = ProjectionCell(ProjectionCellKey(uuid4(), "standard_v1", "count"), 0, "3")
    with pytest.raises(CheckpointConflict, match="canonical root"):
        store.commit_projection_page(_transition(scope, events, stop=1, cells=(cell,)))
    assert store.read_checkpoint_head(scope).through_sequence == -1


def test_new_migration_only_extends_derived_cells():
    from agent_storage.postgres.migrations import MIGRATIONS

    # Exact previous source catalog is read in a separate process by the parent
    # stable baseline; here enforce additive version and immutable named migration.
    current = MIGRATIONS[-1]
    assert current.version == 116 and current.name == "standard_projection_cells"
    assert "session_events" not in "\n".join(current.statements)
