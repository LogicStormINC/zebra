"""Coverage reconnect reconstructs absolute counts, not replayed increments."""

import pytest
from agent_core.domain.coverage_persistence import CoverageRunBinding
from agent_core.domain.events import EventActor, EventType, SessionEvent
from agent_core.domain.identifiers import new_event_id
from agent_integrations.ag_ui import AgUiProjector, AgUiRunIdentity
from agent_integrations.ag_ui.contracts import AgUiProjectionError

from tests.agent_core.test_coverage_contracts import NOW
from tests.agent_core.test_coverage_persistence import binding


def stream(*, last_count=2):
    intent = binding()
    common = {"run_id": intent.run_id, "namespace": intent.namespace}
    events = tuple(
        SessionEvent(
            event_id=new_event_id(), session_id=intent.session_id, sequence=index,
            event_type=kind, actor=EventActor.SYSTEM, created_at=NOW,
            payload=common | payload,
        )
        for index, (kind, payload) in enumerate((
            (EventType.COVERAGE_MANIFEST_COMMITTED, {
                "binding": intent.model_dump(mode="json"), "expected_count": 4,
            }),
            (EventType.COVERAGE_BATCH_ACCEPTED, {"result_count": 2}),
            (EventType.COVERAGE_BATCH_ACCEPTED, {"result_count": last_count}),
            (EventType.COVERAGE_RUN_CANCELLED, {}),
        ), start=1)
    )
    return events, AgUiRunIdentity(session_id=intent.session_id, thread_id="task", run_id="segment")


def progress(projection):
    return [event.value for event in projection.events
            if getattr(event, "name", None) == "zebra.coverage_progress"]


def test_full_replay_and_reconnect_have_the_same_absolute_state():
    events, identity = stream()
    projector = AgUiProjector()
    cursor = projector.project(events[:2], identity).next_cursor
    full = progress(projector.project(events, identity))
    tail = progress(projector.project(events, identity, after=cursor))
    assert [item["accepted_units"] for item in full] == [0, 2, 4, 4]
    assert tail == full[2:]
    assert full[2]["phase"] == "processing"  # all units is not certification
    assert full[-1]["phase"] == "cancelled"
    assert full[-1]["source_watermark"] == 4
    assert all("report_ref" not in item and "_binding" not in item for item in full)


@pytest.mark.parametrize("bad", [True, -1, 0, 3, "2"])
def test_invalid_or_excess_acceptance_fails_closed(bad):
    events, identity = stream(last_count=bad)
    with pytest.raises(AgUiProjectionError):
        AgUiProjector().project(events, identity)


def test_tail_without_original_manifest_cannot_fabricate_progress():
    events, identity = stream()
    with pytest.raises(AgUiProjectionError):
        AgUiProjector().project(events[1:], identity)


def test_certificate_is_historical_progress_not_download_authority():
    events, identity = stream()
    intent = CoverageRunBinding.model_validate(events[0].payload["binding"])
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
        "event_watermark": 4, "created_at": NOW.isoformat(),
        "expires_at": snapshot.expires_at.isoformat(),
    }
    certified = events[-1].model_copy(update={
        "event_type": EventType.COVERAGE_REPORT_CERTIFIED,
        "payload": events[-1].payload | {"certificate": certificate, "report_ref": "secret-ref"},
    })
    receipt = progress(AgUiProjector().project((*events[:3], certified), identity))[-1]
    assert receipt["phase"] == "certified" and "report_ref" not in receipt
    for change in ({"event_watermark": 3}, {"scope_digest": "b" * 64}, {"processed_units": 3}):
        forged = certified.model_copy(update={
            "payload": certified.payload | {"certificate": certificate | change},
        })
        with pytest.raises(AgUiProjectionError):
            AgUiProjector().project((*events[:3], forged), identity)
