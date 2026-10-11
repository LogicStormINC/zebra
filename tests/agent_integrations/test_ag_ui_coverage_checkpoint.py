"""Strict cold replay uses only source metadata, current body and keyed authority."""

import json
from dataclasses import replace

import pytest
from agent_core.domain.coverage_persistence import CoverageRunBinding
from agent_core.domain.events import EventType
from agent_core.ports.agent_tasks import TaskEventPage
from agent_core.ports.task_projection_checkpoints import (
    CheckpointNotReady,
    ProjectionCell,
)
from agent_integrations.ag_ui.checkpoint_materializer import AgUiCheckpointMaterializer
from agent_integrations.ag_ui.checkpoint_observer import AgUiCheckpointObserver
from agent_integrations.ag_ui.checkpoint_plan import (
    ProjectionPagePlan,
    checkpoint_version,
)
from agent_integrations.ag_ui.contracts import AgUiProjectionError
from agent_integrations.ag_ui.coverage_checkpoint import (
    coverage_chunk_count,
    coverage_keys,
)
from agent_integrations.ag_ui.task_stream import AgUiTaskProjector

from tests.agent_core.test_coverage_contracts import NOW
from tests.agent_core.test_coverage_persistence import binding
from tests.agent_integrations.test_ag_ui_projection_checkpoint import (
    IDENTITY,
    TASK,
    A,
    MemoryCheckpoints,
    event,
    materialize,
    plans,
    restored,
)


def sources(marker=None):
    intent = binding().model_copy(update={"session_id": A, "task_id": TASK})
    common = {"run_id": intent.run_id, "namespace": intent.namespace}
    return (
        event(0, EventType.MODEL_RESPONSE_RECEIVED, {"assistant_message": "PRIVATE_PREFIX"}),
        event(1, EventType.TASK_PREPARED, {"coverage_admission": marker}),
        event(2, EventType.COVERAGE_MANIFEST_COMMITTED, common | {
            "binding": intent.model_dump(mode="json"), "expected_count": 4,
        }),
        event(3, EventType.COVERAGE_BATCH_ACCEPTED, common | {"result_count": 2}),
        event(4, EventType.MODEL_RESPONSE_RECEIVED, {"assistant_message": "PRIVATE_TAIL"}),
        event(5, EventType.COVERAGE_BATCH_ACCEPTED, common | {"result_count": 2}),
        event(6, EventType.COVERAGE_RUN_CANCELLED, common),
    )


@pytest.mark.parametrize("chunk", [1, 2, 256])
@pytest.mark.parametrize("marker", [None, {}, "malformed"])
def test_late_marker_cold_restore_and_every_frame_resume_match_full_history(chunk, marker):
    entries = sources(marker)
    port, scope = materialize(entries, chunk)
    expected = list(AgUiTaskProjector().project_task_events(entries, IDENTITY))
    # Recreate the materializer and projector for every Event: no warm Python
    # state or original manifest body is available to the restore path.
    actual = restored(port, scope, entries)
    assert actual == expected
    assert "PRIVATE" not in str(actual)
    progress = [frame.value for _, frame in actual
                if getattr(frame, "name", None) == "zebra.coverage_progress"]
    assert [row["accepted_units"] for row in progress] == [0, 2, 4, 4]
    assert all("_binding" not in row for row in progress)
    for cursor, _ in expected:
        suffix = list(AgUiCheckpointMaterializer(port).iter_event_frames(
            scope, entries[cursor.sequence], IDENTITY, run=port.runs[scope], after=cursor,
        ))
        assert suffix == [(c, f) for c, f in expected
                          if c.sequence == cursor.sequence and c.frame_index > cursor.frame_index]
    assert all(len(keys) <= 1024 for _, keys in port.requests)
    assert all(len((row.value or "").encode()) <= 2048 for _, row in port.cells)


def test_wrong_privacy_plan_cannot_publish_a_visible_prefix():
    entries = sources()
    scope, run, decisions = plans(entries)
    ordinary = replace(run, strict_coverage=False)
    scope = replace(scope, projector_version=checkpoint_version(ordinary))
    port = MemoryCheckpoints(entries)
    with pytest.raises(AgUiProjectionError, match="privacy metadata"):
        AgUiCheckpointMaterializer(port).prepare_page(
            TaskEventPage(entries, -1, run.highwater, 100),
            ProjectionPagePlan(ordinary, decisions), scope, IDENTITY,
        )
    assert not port.cells and not port.headers


def test_new_strict_snapshot_never_uses_old_ordinary_headers():
    ordinary = (event(0, EventType.MODEL_RESPONSE_RECEIVED, {"assistant_message": "PRIVATE"}),)
    port, old_scope = materialize(ordinary)
    rows = (*ordinary, event(1, EventType.TASK_PREPARED, {"coverage_admission": None}))
    _, current, _ = plans(rows)
    port.read_run_header = lambda *a, **k: current
    observer = AgUiCheckpointObserver(port, namespace=old_scope.namespace)
    snapshot = observer.snapshot(TASK, IDENTITY)
    assert snapshot.head.scope.projector_version != old_scope.projector_version
    assert snapshot.head.through_sequence == -1
    assert observer.read_page(snapshot, -1) is None
    with pytest.raises(AgUiProjectionError, match="projector version"):
        AgUiCheckpointMaterializer(port).restore_event_frames(
            old_scope, ordinary[0], IDENTITY, run=current,
        )


def test_privacy_flip_during_observation_stops_before_next_frame():
    rows = (event(0, EventType.MODEL_RESPONSE_RECEIVED, {"assistant_message": "PRIVATE"}),)
    port, scope = materialize(rows)
    original = port.runs[scope]
    current = original
    port.read_run_header = lambda *a, **k: current
    observer = AgUiCheckpointObserver(port, namespace=scope.namespace)
    snapshot = observer.snapshot(TASK, IDENTITY)
    frames = observer.iter_page_frames(snapshot, TaskEventPage(rows, -1, 0, 100), IDENTITY)
    assert "PRIVATE" not in str(next(frames))  # RUN_STARTED owns frame zero.
    current = replace(original, strict_coverage=True)
    with pytest.raises(CheckpointNotReady, match="privacy changed"):
        next(frames)


@pytest.mark.parametrize(
    "corruption", ["missing_chunk", "bad_count", "foreign_binding", "bool_count"]
)
def test_missing_or_contradictory_manifest_authority_fails_closed(corruption):
    entries = sources()
    port, scope = materialize(entries, 1)
    target = entries[3]
    keys = coverage_keys(target.event)
    metadata = port.read_cells_at(scope, target.task_sequence, keys)
    count = coverage_chunk_count(target.event, metadata)
    chunks = port.read_cells_at(scope, target.task_sequence, coverage_keys(target.event, count)[1:])
    selected = {(row.key, row.task_sequence) for row in (*metadata, *chunks)}
    if corruption in {"foreign_binding", "bool_count"}:
        decoded = json.loads("".join(row.value for row in chunks))
        if corruption == "foreign_binding":
            decoded["_binding"]["run_id"] = "foreign"
        else:
            decoded["accepted_units"] = True
        encoded = json.dumps(decoded, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
        values = tuple(encoded[i:i + 2048] for i in range(0, len(encoded), 2048))
        replacements = [ProjectionCell(key, 2, value) for key, value in zip(
            coverage_keys(target.event, len(values)), (str(len(values)), *values), strict=True
        )]
    elif corruption == "missing_chunk":
        replacements = list(metadata)
    else:
        replacements = [replace(metadata[0], value="1024"), *chunks]
    port.cells = [(owner, row) for owner, row in port.cells
                  if owner != scope or (row.key, row.task_sequence) not in selected]
    port.cells.extend((scope, row) for row in replacements)
    with pytest.raises(AgUiProjectionError):
        AgUiCheckpointMaterializer(port).restore_event_frames(
            scope, target, IDENTITY, run=port.runs[scope],
        )


def test_replayed_manifest_cannot_restart_accepted_counts():
    entries = sources()
    repeated = event(7, EventType.COVERAGE_MANIFEST_COMMITTED, entries[2].event.payload)
    port, scope = materialize(entries, 1)
    all_rows = (*entries, repeated)
    _, run, decisions = plans(all_rows)
    with pytest.raises(AgUiProjectionError, match="manifest conflicts"):
        AgUiCheckpointMaterializer(port).prepare_page(
            TaskEventPage((repeated,), 6, 7, 100), ProjectionPagePlan(run, decisions[7:]),
            scope, IDENTITY,
        )
    assert port.read_checkpoint_head(scope).through_sequence == 6


@pytest.mark.parametrize("chunk", [1, 256])
def test_cold_certification_restores_original_authority_without_download_ref(chunk):
    entries = sources()
    intent = CoverageRunBinding.model_validate(entries[2].event.payload["binding"])
    snapshot = intent.snapshot
    certificate = {
        "namespace": intent.namespace, "host_id": snapshot.host_id,
        "snapshot_id": snapshot.snapshot_id, "authority_revision": snapshot.authority_revision,
        "contract_revision": intent.contract.contract_revision,
        "contract_digest": intent.contract.digest, "scope_digest": intent.contract.scope.digest,
        "manifest_digest": snapshot.manifest_digest, "enumerated_records": 2,
        "read_parts": 2, "processed_units": 4, "reviewed_units": 0,
        "result_set_digest": "a" * 64, "aggregate_digest": "a" * 64,
        "report_digest": "a" * 64, "validator_version": "exact-artifact/1",
        "event_watermark": 6, "created_at": NOW.isoformat(),
        "expires_at": snapshot.expires_at.isoformat(),
    }
    certified = event(6, EventType.COVERAGE_REPORT_CERTIFIED, entries[-1].event.payload | {
        "certificate": certificate, "report_ref": "PRIVATE_DOWNLOAD_REF",
    })
    entries = (*entries[:-1], certified)
    port, scope = materialize(entries, chunk)
    actual = restored(port, scope, entries)
    assert actual == list(AgUiTaskProjector().project_task_events(entries, IDENTITY))
    assert actual[-1][1].value["phase"] == "certified"
    assert actual[-1][1].value["accepted_units"] == 4
    assert "PRIVATE" not in str(actual)
    for change in ({"event_watermark": 5}, {"scope_digest": "b" * 64}, {"processed_units": 3}):
        forged = replace(certified, event=certified.event.model_copy(update={
            "payload": certified.event.payload | {"certificate": certificate | change},
        }))
        with pytest.raises(AgUiProjectionError, match="certificate conflicts"):
            AgUiCheckpointMaterializer(port).restore_event_frames(
                scope, forged, IDENTITY, run=port.runs[scope],
            )


def test_multichunk_nonascii_manifest_uses_bounded_cells_not_original_body():
    entries = list(sources())
    intent = CoverageRunBinding.model_validate(entries[2].event.payload["binding"])
    snapshot = intent.snapshot.model_copy(update={
        "manifest_artifact_ref": "artifact://" + "雪" * 1500,
    })
    intent = intent.model_copy(update={"snapshot": snapshot})
    entries[2] = replace(entries[2], event=entries[2].event.model_copy(update={
        "payload": entries[2].event.payload | {"binding": intent.model_dump(mode="json")},
    }))
    port, scope = materialize(entries, 1)
    target = entries[3]
    metadata = port.read_cells_at(scope, target.task_sequence, coverage_keys(target.event))
    assert coverage_chunk_count(target.event, metadata) > 2
    actual = restored(port, scope, entries)
    assert actual == list(AgUiTaskProjector().project_task_events(entries, IDENTITY))
    assert all(len((row.value or "").encode()) <= 2048 for _, row in port.cells)
    assert "artifact://" not in str(actual)
