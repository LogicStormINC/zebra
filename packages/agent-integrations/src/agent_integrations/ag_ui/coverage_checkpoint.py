"""Bounded keyed persistence of the existing coverage progress reducer."""

import json

from agent_core.domain.coverage_persistence import CoverageRunBinding
from agent_core.domain.events import EventType, SessionEvent
from agent_core.ports.task_projection_checkpoints import (
    MAX_CHECKPOINT_KEYS,
    ProjectionCell,
    ProjectionCellKey,
)

from agent_integrations.ag_ui.contracts import AgUiProjectionError
from agent_integrations.ag_ui.payload_validation import required_payload_text
from agent_integrations.ag_ui.projection_state import ProjectionState

_PROGRESS = frozenset({
    EventType.COVERAGE_MANIFEST_COMMITTED, EventType.COVERAGE_BATCH_ACCEPTED,
    EventType.COVERAGE_RUN_CANCELLED, EventType.COVERAGE_REPORT_CERTIFIED,
})


def coverage_keys(event: SessionEvent, count: int = 0) -> tuple[ProjectionCellKey, ...]:
    if event.event_type not in _PROGRESS:
        return ()
    run = required_payload_text(event.payload, "run_id")
    return tuple(
        ProjectionCellKey(event.session_id, "coverage", json.dumps([run, index]))
        for index in (None, *range(count))
    )


def coverage_chunk_count(event: SessionEvent, cells: tuple[ProjectionCell, ...]) -> int:
    keys = coverage_keys(event)
    if not keys:
        return 0
    row = next((cell for cell in cells if cell.key == keys[0]), None)
    if row is None:
        return 0
    value = row.value
    if value is None or not value.isascii() or not value.isdecimal() or len(value) > 4:
        raise AgUiProjectionError("coverage checkpoint has invalid chunk metadata")
    count = int(value)
    if not 1 <= count < MAX_CHECKPOINT_KEYS or str(count) != value:
        raise AgUiProjectionError("coverage checkpoint exceeds keyed-state bound")
    return count


def restore_coverage(
    event: SessionEvent, cells: tuple[ProjectionCell, ...], state: ProjectionState
) -> None:
    count = coverage_chunk_count(event, cells)
    if not count:
        return
    by_key = {cell.key: cell for cell in cells}
    keys = coverage_keys(event, count)[1:]
    if any(key not in by_key or by_key[key].value is None for key in keys):
        raise AgUiProjectionError("coverage checkpoint omits manifest state")
    try:
        restored = json.loads("".join(by_key[key].value or "" for key in keys))
        if not isinstance(restored, dict) or set(restored) != {
            "_binding", "schema_version", "run_id", "snapshot_id", "manifest_digest",
            "enumerated_records", "expected_units", "accepted_units", "phase",
            "expires_at", "source_watermark",
        }:
            raise ValueError("invalid coverage state shape")
        binding = CoverageRunBinding.model_validate(restored["_binding"])
        if (
            binding.session_id != event.session_id
            or binding.run_id != required_payload_text(event.payload, "run_id")
            or restored["run_id"] != binding.run_id
            or type(restored["schema_version"]) is not int or restored["schema_version"] != 1
            or restored["snapshot_id"] != binding.snapshot.snapshot_id
            or restored["manifest_digest"] != binding.snapshot.manifest_digest
            or type(restored["enumerated_records"]) is not int
            or restored["enumerated_records"] != binding.snapshot.record_count
            or restored["expires_at"] != binding.snapshot.expires_at.isoformat()
            or type(restored["expected_units"]) is not int
            or type(restored["accepted_units"]) is not int
            or not 0 <= restored["accepted_units"] <= restored["expected_units"]
            or restored["phase"] not in {"processing", "cancelled", "certified"}
            or (restored["phase"] == "certified"
                and restored["accepted_units"] != restored["expected_units"])
            or type(restored["source_watermark"]) is not int
            or not 0 <= restored["source_watermark"] < event.sequence
        ):
            raise ValueError("coverage state conflicts with original manifest")
        restored["_binding"] = binding
        state.coverage_runs[binding.run_id] = restored
    except (ValueError, TypeError, KeyError) as exc:
        raise AgUiProjectionError("coverage checkpoint conflicts with manifest authority") from exc


def coverage_changes(
    event: SessionEvent, state: ProjectionState
) -> tuple[tuple[ProjectionCellKey, str], ...]:
    if not coverage_keys(event):
        return ()
    run = required_payload_text(event.payload, "run_id")
    current = state.coverage_runs.get(run)
    if current is None or not isinstance(current.get("_binding"), CoverageRunBinding):
        raise AgUiProjectionError("coverage checkpoint requires original manifest authority")
    encoded = json.dumps(
        {**current, "_binding": current["_binding"].model_dump(mode="json")},
        sort_keys=True, separators=(",", ":"), ensure_ascii=True, allow_nan=False,
    )
    # ponytail: <=2048 ASCII bytes per existing cell; the shared Page reader
    # enforces the aggregate key/byte ceiling before any atomic publication.
    chunks = tuple(encoded[index:index + 2048] for index in range(0, len(encoded), 2048))
    if not 1 <= len(chunks) < MAX_CHECKPOINT_KEYS:
        raise AgUiProjectionError("coverage checkpoint exceeds keyed-state bound")
    return tuple(zip(coverage_keys(event, len(chunks)), (str(len(chunks)), *chunks), strict=True))
