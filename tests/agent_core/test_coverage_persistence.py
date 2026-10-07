"""Artifact encodings and immutable coverage storage binding regression."""

import json
from hashlib import sha256
from uuid import uuid4

import pytest
from agent_core.domain.coverage_persistence import (
    CoverageRunBinding,
    canonical_coverage_bytes,
    coverage_manifest_bytes,
    coverage_result_bytes,
)
from agent_core.domain.coverage_validation import result_set_digest
from agent_core.domain.identifiers import SessionId, TaskId
from pydantic import ValidationError

from tests.agent_core.test_coverage_contracts import contract, records, results_for, snapshot


def binding(items=None):
    items = records() if items is None else items
    session = uuid4()
    return CoverageRunBinding(
        namespace="tenant-1", session_id=SessionId(session), task_id=TaskId(session),
        run_id="run-1", contract=contract(), snapshot=snapshot(items),
        manifest_artifact_digest=sha256(coverage_manifest_bytes(items)).hexdigest(),
    )


def test_canonical_result_artifact_has_contract_digest():
    results = results_for(records())
    assert sha256(coverage_result_bytes(results)).hexdigest() == result_set_digest(results)
    assert coverage_result_bytes(results[::-1]) == coverage_result_bytes(results)


def test_manifest_and_empty_manifest_are_exactly_bound():
    for items in (records(), ()):
        assert binding(items).verify_manifest(coverage_manifest_bytes(items)) == items


@pytest.mark.parametrize("change", ["duplicate", "missing", "ordinal", "version", "extra"])
def test_manifest_cannot_admit_same_count_wrong_identity(change):
    intent = binding()
    data = json.loads(coverage_manifest_bytes(records()))
    if change == "duplicate":
        data["records"][1] = data["records"][0]
    elif change == "missing":
        data["records"].pop()
    elif change == "ordinal":
        data["records"][1]["ordinal"] = 2
    elif change == "version":
        data["records"][1]["content_digest"] = "f" * 64
    else:
        data["unexpected"] = True
    payload = canonical_coverage_bytes(data)
    intent = intent.model_copy(update={"manifest_artifact_digest": sha256(payload).hexdigest()})
    with pytest.raises(ValueError):
        intent.verify_manifest(payload)


def test_manifest_encoding_and_artifact_hash_fail_closed():
    intent = binding()
    payload = coverage_manifest_bytes(records())
    with pytest.raises(ValueError, match="bytes changed"):
        intent.verify_manifest(payload + b" ")
    changed = payload + b" "
    altered = intent.model_copy(update={"manifest_artifact_digest": sha256(changed).hexdigest()})
    with pytest.raises(ValueError, match="canonical"):
        altered.verify_manifest(changed)


def test_namespace_scope_binding_is_not_a_caller_claim():
    intent = binding()
    with pytest.raises(ValidationError, match="scope"):
        CoverageRunBinding.model_validate({**intent.model_dump(), "namespace": "other"})
