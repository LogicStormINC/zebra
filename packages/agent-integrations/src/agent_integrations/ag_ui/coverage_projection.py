"""Absolute replay-safe progress, never a report publication authorization."""

from typing import Any

from ag_ui.core import CustomEvent
from agent_core.domain.coverage_persistence import CoverageRunBinding
from agent_core.domain.coverage_validation import CoverageCertificate
from agent_core.domain.events import EventType, SessionEvent

from agent_integrations.ag_ui.contracts import AgUiProjectionError


def project_coverage(
    event: SessionEvent, runs: dict[str, dict[str, Any]], *, timestamp: int
) -> CustomEvent | None:
    kind = event.event_type
    if kind not in {
        EventType.COVERAGE_MANIFEST_COMMITTED, EventType.COVERAGE_BATCH_ACCEPTED,
        EventType.COVERAGE_RUN_CANCELLED, EventType.COVERAGE_REPORT_CERTIFIED,
    }:
        return None
    payload = event.payload
    run_id = payload.get("run_id")
    if type(run_id) is not str or not run_id:
        raise AgUiProjectionError("coverage progress has no run identity")
    if kind == EventType.COVERAGE_MANIFEST_COMMITTED:
        binding = CoverageRunBinding.model_validate(payload.get("binding"))
        expected = payload.get("expected_count")
        if (
            binding.run_id != run_id or binding.session_id != event.session_id
            or binding.namespace != payload.get("namespace") or run_id in runs
            or type(expected) is not int or expected < 0
        ):
            raise AgUiProjectionError("coverage progress manifest conflicts")
        runs[run_id] = {
            "_binding": binding,
            "schema_version": 1, "run_id": run_id,
            "snapshot_id": binding.snapshot.snapshot_id,
            "manifest_digest": binding.snapshot.manifest_digest,
            "enumerated_records": binding.snapshot.record_count,
            "expected_units": expected, "accepted_units": 0,
            "phase": "processing", "expires_at": binding.snapshot.expires_at.isoformat(),
        }
    state = runs.get(run_id)
    if state is None:
        raise AgUiProjectionError("coverage progress requires its original manifest")
    if kind == EventType.COVERAGE_BATCH_ACCEPTED:
        count = payload.get("result_count")
        if (
            state["phase"] != "processing" or type(count) is not int or count <= 0
            or state["accepted_units"] + count > state["expected_units"]
        ):
            raise AgUiProjectionError("coverage progress acceptance conflicts")
        state["accepted_units"] += count
    elif kind == EventType.COVERAGE_RUN_CANCELLED:
        state["phase"] = "cancelled"
    elif kind == EventType.COVERAGE_REPORT_CERTIFIED:
        certificate = CoverageCertificate.model_validate(payload.get("certificate"))
        binding = state["_binding"]
        if (
            state["phase"] != "processing"
            or certificate.snapshot_id != state["snapshot_id"]
            or certificate.manifest_digest != state["manifest_digest"]
            or certificate.enumerated_records != state["enumerated_records"]
            or certificate.processed_units != state["accepted_units"]
            or state["accepted_units"] != state["expected_units"]
            or certificate.event_watermark != event.sequence
            or certificate.namespace != binding.namespace
            or certificate.host_id != binding.snapshot.host_id
            or certificate.authority_revision != binding.snapshot.authority_revision
            or certificate.contract_digest != binding.contract.digest
            or certificate.scope_digest != binding.contract.scope.digest
            or certificate.contract_revision != binding.contract.contract_revision
            or certificate.expires_at != binding.snapshot.expires_at
        ):
            raise AgUiProjectionError("coverage progress certificate conflicts")
        # A historical certificate cannot authorize a present-day download.
        state["phase"] = "certified"
    state["source_watermark"] = event.sequence
    return CustomEvent(
        timestamp=timestamp, name="zebra.coverage_progress",
        value={key: value for key, value in state.items() if not key.startswith("_")},
    )
