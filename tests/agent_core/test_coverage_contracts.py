import hashlib
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from agent_core.domain.coverage_contracts import (
    CoverageCheck,
    CoverageContract,
    CoverageRefusedError,
    CoverageScope,
    coverage_digest,
)
from agent_core.domain.coverage_snapshot import (
    CoveragePage,
    CoveragePageRequest,
    CoveragePart,
    CoverageRecord,
    CoverageSnapshot,
)
from agent_core.domain.coverage_validation import (
    AcceptedCoverageUnit,
    CoverageCertificate,
    CoverageValidationEvidence,
    expected_units,
    manifest_digest,
    result_set_digest,
    validate_coverage,
)
from agent_core.ports.coverage import CoverageCommit
from pydantic import ValidationError

NOW = datetime(2026, 10, 7, tzinfo=UTC)
DIGEST = "a" * 64


def contract() -> CoverageContract:
    return CoverageContract(
        scope=CoverageScope(
            timezone="Asia/Shanghai", from_inclusive=NOW, to_exclusive=NOW + timedelta(days=1)
        ),
        checks=(CoverageCheck(id="risk", version="1", kind="model", definition_digest=DIGEST),),
    )


def records(count: int = 2) -> tuple[CoverageRecord, ...]:
    return tuple(
        CoverageRecord(
            ordinal=index,
            record_id=f"event-{index}",
            content_digest=f"{index:064x}",
            parts=(CoveragePart(id="body-0", digest=DIGEST, byte_length=3),),
        )
        for index in range(count)
    )


def snapshot(items: tuple[CoverageRecord, ...]) -> CoverageSnapshot:
    spec = contract()
    return CoverageSnapshot(
        namespace="tenant-1",
        host_id="trench",
        snapshot_id="snapshot-1",
        authority_revision="grant-1",
        contract_digest=spec.digest,
        scope_digest=spec.scope.digest,
        manifest_digest=manifest_digest(spec, items),
        record_count=len(items),
        manifest_artifact_ref="artifact://manifest-1",
        as_of=NOW,
        expires_at=NOW + timedelta(hours=2),
    )


def evidence(results: tuple[AcceptedCoverageUnit, ...]) -> CoverageValidationEvidence:
    return CoverageValidationEvidence(
        namespace="tenant-1",
        host_id="trench",
        snapshot_id="snapshot-1",
        authority_revision="grant-1",
        authority_valid=True,
        artifacts_readable=True,
        upstream_ready=True,
        aggregate_result_set_digest=result_set_digest(results),
    )


def results_for(items: tuple[CoverageRecord, ...]) -> tuple[AcceptedCoverageUnit, ...]:
    return tuple(
        AcceptedCoverageUnit(key=key, result_digest=DIGEST, outcome="clear")
        for key in expected_units(contract(), items)
    )


def verdict(items: tuple[CoverageRecord, ...], results: tuple[AcceptedCoverageUnit, ...]):
    return validate_coverage(
        contract=contract(),
        snapshot=snapshot(items),
        manifest=items,
        enumerated=tuple(item.identity for item in items),
        read_parts=tuple(part_key for item in items for part_key in item.part_keys),
        accepted=results,
        evidence=evidence(results),
        now=NOW,
    )


def test_exact_coverage_requires_negative_results_and_record_merge():
    items = records()
    results = results_for(items)
    assert len(results) == 4
    assert verdict(items, results).complete
    assert not verdict(items, results[:-1]).complete


def test_same_count_with_duplicate_or_extra_identity_fails():
    items = records()
    results = results_for(items)
    assert not verdict(items, results[:-1] + (results[0],)).complete
    forged = results[-1].model_copy(
        update={"key": results[-1].key.model_copy(update={"record_id": "invented"})}
    )
    assert not verdict(items, results[:-1] + (forged,)).complete


def test_large_manifest_and_empty_authorized_snapshot():
    items = records(10_003)
    assert verdict(items, results_for(items)).complete
    empty = verdict((), ())
    assert empty.complete
    assert empty.processed_ratio is None


@pytest.mark.parametrize(
    "update",
    [
        {"content_requirements": ("attachments",)},
        {"cross_record_checks": ("relations",)},
        {"unresolved_policy": "waive"},
        {"mode": "exploratory"},
        {"contract_revision": True},
        {"schema_version": 2},
        {"schema_version": True},
        {"filters": {"keyword": "oil"}},
    ],
)
def test_contract_refuses_unsupported_or_weakened_requests(update):
    with pytest.raises(ValidationError):
        CoverageContract.model_validate(contract().model_dump() | update)


@pytest.mark.parametrize(
    "update",
    [
        {"from_inclusive": NOW.replace(tzinfo=None)},
        {"from_inclusive": 0},
        {"to_exclusive": NOW},
        {"timezone": "not/a-zone"},
        {"source_selection": "top_120"},
    ],
)
def test_scope_is_finite_aware_and_unfiltered(update):
    with pytest.raises(ValidationError):
        CoverageScope.model_validate(contract().scope.model_dump() | update)


def test_scope_uses_same_digest_for_equivalent_instants():
    spec = contract()
    shifted = spec.scope.model_dump(mode="json")
    shifted["from_inclusive"] = "2026-10-07T08:00:00+08:00"
    assert CoverageScope.model_validate(shifted).digest == spec.scope.digest
    assert CoverageContract.model_validate_json(spec.model_dump_json()) == spec


def test_check_definition_changes_unit_identity():
    spec = contract()
    changed = CoverageContract.model_validate(
        spec.model_dump()
        | {"checks": (spec.checks[0].model_dump() | {"definition_digest": "b" * 64},)}
    )
    assert expected_units(spec, records()) != expected_units(changed, records())


def test_duplicate_checks_and_parts_are_rejected():
    spec = contract()
    with pytest.raises(ValidationError):
        CoverageContract.model_validate(spec.model_dump() | {"checks": spec.checks * 2})
    item = records()[0]
    with pytest.raises(ValidationError):
        CoverageRecord.model_validate(item.model_dump() | {"parts": item.parts * 2})


@pytest.mark.parametrize(
    "failure",
    [
        "missing_read",
        "extra_read",
        "missing_enumeration",
        "duplicate_enumeration",
        "version_drift",
        "manifest_drift",
        "authority",
        "artifacts",
        "upstream",
        "expiry",
        "reviews",
        "failures",
        "aggregate",
        "namespace",
        "host_id",
        "snapshot_id",
        "authority_revision",
    ],
)
def test_each_required_proof_fails_closed(failure):
    items = records()
    results = results_for(items)
    snap = snapshot(items)
    proof = evidence(results)
    enumerated = tuple(item.identity for item in items)
    read = tuple(key for item in items for key in item.part_keys)
    if failure == "missing_read":
        read = read[:-1]
    elif failure == "extra_read":
        read += (read[0],)
    elif failure == "missing_enumeration":
        enumerated = enumerated[:-1]
    elif failure == "duplicate_enumeration":
        enumerated = enumerated[:-1] + (enumerated[0],)
    elif failure == "version_drift":
        enumerated = enumerated[:-1] + ((items[-1].record_id, "b" * 64),)
    elif failure == "manifest_drift":
        snap = snap.model_copy(update={"manifest_digest": "b" * 64})
    elif failure in {"authority", "artifacts", "upstream"}:
        field = {
            "authority": "authority_valid",
            "artifacts": "artifacts_readable",
            "upstream": "upstream_ready",
        }[failure]
        proof = proof.model_copy(update={field: False})
    elif failure == "expiry":
        snap = snap.model_copy(update={"expires_at": NOW})
    elif failure in {"reviews", "failures"}:
        proof = proof.model_copy(update={f"unresolved_{failure}": 1})
    elif failure == "aggregate":
        proof = proof.model_copy(update={"aggregate_result_set_digest": "b" * 64})
    elif failure in {"namespace", "host_id", "snapshot_id", "authority_revision"}:
        proof = proof.model_copy(update={failure: "another-binding"})
    result = validate_coverage(
        contract=contract(),
        snapshot=snap,
        manifest=items,
        enumerated=enumerated,
        read_parts=read,
        accepted=results,
        evidence=proof,
        now=NOW,
    )
    assert not result.complete
    assert result.reasons


def test_body_bytes_are_verified_without_splitting_utf8():
    body = "正文🙂".encode()
    part = CoveragePart(id="body", digest=hashlib.sha256(body).hexdigest(), byte_length=len(body))
    part.verify_bytes(body)
    with pytest.raises(CoverageRefusedError):
        part.verify_bytes(body[:-1])
    with pytest.raises(CoverageRefusedError):
        part.verify_bytes(b"x" * len(body))


@pytest.mark.parametrize(
    "update",
    [
        {"namespace": "another"},
        {"snapshot_id": "another"},
        {"scope_digest": "b" * 64},
        {"next_cursor": "same"},
        {"records": records()},
    ],
)
def test_page_is_bound_to_request_and_bounded(update):
    request = CoveragePageRequest(
        namespace="tenant-1",
        snapshot_id="snapshot-1",
        scope_digest=DIGEST,
        page_size=1,
        cursor="same",
    )
    page = CoveragePage(
        namespace=request.namespace,
        snapshot_id=request.snapshot_id,
        scope_digest=request.scope_digest,
        records=records(1),
        next_cursor=None,
    )
    page.validate_for(request)
    with pytest.raises(CoverageRefusedError):
        CoveragePage.model_validate(page.model_dump() | update).validate_for(request)


def test_commit_requires_unique_units_and_exact_artifact_digest():
    results = results_for(records())
    payload = {
        "namespace": "tenant-1",
        "session_id": uuid4(),
        "task_id": uuid4(),
        "run_id": "run-1",
        "snapshot_id": "snapshot-1",
        "contract_digest": contract().digest,
        "manifest_digest": snapshot(records()).manifest_digest,
        "commit_key": "commit-1",
        "result_artifact_ref": "artifact://results",
        "result_artifact_digest": result_set_digest(results),
        "results": results,
    }
    assert (
        CoverageCommit.model_validate_json(
            CoverageCommit.model_validate(payload).model_dump_json()
        ).results
        == results
    )
    duplicate = results + (results[0],)
    with pytest.raises(ValidationError):
        CoverageCommit.model_validate(
            payload
            | {
                "results": duplicate,
                "result_artifact_digest": result_set_digest(duplicate),
            }
        )
    with pytest.raises(ValidationError):
        CoverageCommit.model_validate(payload | {"result_artifact_digest": "b" * 64})


def test_canonical_digest_is_explicit_utf8_null_and_rejects_nan():
    assert coverage_digest({"正文": None, "n": 1}) == coverage_digest({"n": 1, "正文": None})
    assert coverage_digest({"n": None}) != coverage_digest({})
    with pytest.raises(ValueError):
        coverage_digest({"n": float("nan")})


def test_out_of_order_manifest_and_results_have_stable_digests():
    items = records()
    results = results_for(items)
    assert manifest_digest(contract(), items) == manifest_digest(contract(), items[::-1])
    assert result_set_digest(results) == result_set_digest(results[::-1])
    assert verdict(items[::-1], results[::-1]).complete


def test_manifest_cannot_reseal_duplicate_records_or_noncontiguous_ordinals():
    for invalid in (
        (records()[0], records()[0]),
        (records()[0], records()[1].model_copy(update={"ordinal": 3})),
    ):
        assert not verdict(invalid, results_for(invalid)).complete


def test_snapshot_shape_and_scope_version_changes_fail_closed():
    items = records()
    snap = snapshot(items)
    for update in (
        {"schema_version": True},
        {"state": "preparing"},
        {"record_count": True},
        {"expires_at": NOW},
        {"manifest_artifact_ref": " "},
    ):
        with pytest.raises(ValidationError):
            CoverageSnapshot.model_validate(snap.model_dump() | update)
    results = results_for(items)
    changed = CoverageContract.model_validate(contract().model_dump() | {"contract_revision": 2})
    result = validate_coverage(
        contract=changed,
        snapshot=snap,
        manifest=items,
        enumerated=tuple(item.identity for item in items),
        read_parts=tuple(key for item in items for key in item.part_keys),
        accepted=results,
        evidence=evidence(results),
        now=NOW,
    )
    assert not result.complete


def test_contract_is_immutable_and_does_not_mutate_host_input():
    payload = contract().model_dump(mode="json")
    spec = CoverageContract.model_validate(payload)
    payload["checks"][0]["version"] = "later"
    assert spec.checks[0].version == "1"
    with pytest.raises(ValidationError):
        spec.contract_revision = 2


def test_certificate_is_bounded_receipt_not_an_unvalidated_success_message():
    payload = {
        "namespace": "tenant-1",
        "host_id": "trench",
        "snapshot_id": "snapshot-1",
        "authority_revision": "grant-1",
        "contract_revision": 1,
        "contract_digest": DIGEST,
        "scope_digest": DIGEST,
        "manifest_digest": DIGEST,
        "enumerated_records": 2,
        "read_parts": 2,
        "processed_units": 4,
        "reviewed_units": 1,
        "result_set_digest": DIGEST,
        "aggregate_digest": DIGEST,
        "report_digest": DIGEST,
        "validator_version": "1",
        "event_watermark": 5,
        "created_at": NOW,
        "expires_at": NOW + timedelta(hours=1),
    }
    receipt = CoverageCertificate.model_validate(payload)
    assert CoverageCertificate.model_validate_json(receipt.model_dump_json()) == receipt
    for update in (
        {"schema_version": True},
        {"expires_at": NOW},
        {"reviewed_units": 5},
        {"event_watermark": 0},
        {"processed_units": True},
        {"report_digest": "short"},
        {"complete": True},
    ):
        with pytest.raises(ValidationError):
            CoverageCertificate.model_validate(payload | update)


def test_unaccepted_model_outcomes_cannot_enter_a_result_batch():
    for outcome in ("unknown", "failed", "review_required", "waived"):
        with pytest.raises(ValidationError):
            AcceptedCoverageUnit.model_validate(
                {
                    "key": expected_units(contract(), records())[0],
                    "result_digest": DIGEST,
                    "outcome": outcome,
                }
            )
