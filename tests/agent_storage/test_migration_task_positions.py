"""Published coordinates are validated independently of the offline import IO."""

from uuid import UUID, uuid4

import pytest
from agent_storage.postgres.migration_snapshot import SnapshotRecord
from agent_storage.postgres.migration_task_positions import (
    TaskPositionMigrationError,
    snapshot_task_positions,
)


def _record(session: str, sequence: int, task: object, position: object) -> SnapshotRecord:
    return SnapshotRecord(
        "session_events",
        ("event_id", "session_id", "sequence", "task_id", "task_sequence"),
        (str(uuid4()), session, sequence, task, position),
    )


@pytest.mark.parametrize("task,position", [
    (None, 0), (str(uuid4()), None), (str(uuid4()), -1), (str(uuid4()), True),
    (str(uuid4()), 0.5), ("invalid", 0), (str(uuid4()), 1),
])
def test_import_rejects_invalid_position_metadata(task: object, position: object) -> None:
    with pytest.raises(TaskPositionMigrationError):
        snapshot_task_positions([_record(str(uuid4()), 0, task, position)])


def test_import_preserves_interleaved_segments_and_late_predecessor_metadata() -> None:
    root, child = str(uuid4()), str(uuid4())
    records = [
        _record(root, 0, root, 0), _record(root, 1, root, 1),
        _record(child, 0, root, 2), _record(root, 2, root, 3),
    ]
    assigned = snapshot_task_positions(list(reversed(records)))
    assert [assigned[UUID(str(record.values[0]))][1] for record in records] == [
        0, 1, 2, 3,
    ]


@pytest.mark.parametrize("fault", ["duplicate", "inverted", "missing-prefix", "foreign-task"])
def test_import_rejects_ambiguous_or_reordered_source_prefix(fault: str) -> None:
    root = str(uuid4())
    first = _record(root, 0, root, 0)
    second = _record(root, 1, root, 1)
    if fault == "duplicate":
        second = _record(root, 1, root, 0)
    elif fault == "inverted":
        first, second = _record(root, 0, root, 1), _record(root, 1, root, 0)
    elif fault == "missing-prefix":
        first, second = _record(root, 0, None, None), _record(root, 1, root, 0)
    else:
        second = _record(root, 1, str(uuid4()), 0)
    with pytest.raises(TaskPositionMigrationError):
        snapshot_task_positions([first, second])


def test_unassigned_legacy_tail_remains_unassigned_until_canonical_import() -> None:
    root = str(uuid4())
    first = _record(root, 0, root, 0)
    assigned = snapshot_task_positions([first, _record(root, 1, None, None)])
    assert len(assigned) == 1
