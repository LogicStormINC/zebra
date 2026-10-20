"""Versioned opaque selection admissions preserve the frozen source boundary."""

import pytest
from agent_core.application.coverage_admission import validate_coverage_admission
from agent_core.domain.coverage_contracts import CoverageContract
from agent_core.domain.coverage_task_admission import CoverageTaskAdmission
from agent_core.domain.host_authority import HostResourceRef

from tests.agent_core.test_coverage_task_admission import NOW, admission, host


def neutral_admission():
    raw = admission().model_dump(mode="json")
    raw.pop("history_ref")
    raw["source_ref"] = {"type": "archive.collection", "id": "collection-1"}
    raw["contract"].update(
        {
            "schema_version": 2,
            "dataset": "archive.documents",
            "dataset_revision": "7",
            "source": {
                "protocol": "coverage-source/2",
                "resource_type": "archive.collection",
                "read_scope": "collection.read",
                "create_scope": "collection.snapshot.create",
            },
            "scope": {"selection_ref": "opaque", "selection_digest": "a" * 64},
        }
    )
    return raw


def neutral_host():
    return host().model_copy(
        update={
            "host_app_id": "archive",
            "resource_refs": (HostResourceRef(type="archive.collection", id="collection-1"),),
            "scopes": ("collection.read", "collection.snapshot.create"),
        }
    )


def test_neutral_admission_binds_exact_resource_and_opaque_selection():
    raw = neutral_admission()
    value = validate_coverage_admission(raw, host_context=neutral_host(), now=NOW)
    assert value.source_resource == neutral_host().resource_refs[0]
    assert "history_ref" not in value.model_dump(mode="json")
    restored = CoverageTaskAdmission.model_validate(value.model_dump(mode="json"))
    assert restored == value and restored.contract.digest == value.contract.digest
    for scopes in [("collection.read",), ("history.read", "history.snapshot.write")]:
        with pytest.raises(ValueError):
            validate_coverage_admission(
                raw, host_context=neutral_host().model_copy(update={"scopes": scopes}), now=NOW
            )


@pytest.mark.parametrize(
    "field,value", [("resource_type", "other"), ("protocol", "coverage-source/1")]
)
def test_v2_source_rejects_mismatch(field, value):
    raw = neutral_admission()
    raw["contract"]["source"][field] = value
    with pytest.raises(ValueError):
        CoverageTaskAdmission.model_validate(raw)


def test_v2_fields_are_bounded_frozen_and_digest_bound():
    contract = CoverageTaskAdmission.model_validate(neutral_admission()).contract
    for key in ("dataset", "dataset_revision"):
        for value in ("", " ", "x" * 257):
            with pytest.raises(ValueError):
                CoverageContract.model_validate({**contract.model_dump(), key: value})
        assert (
            CoverageContract.model_validate({**contract.model_dump(), key: "other"}).digest
            != contract.digest
        )
    with pytest.raises(ValueError):
        contract.source.read_scope = "weaker"
