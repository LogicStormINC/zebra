"""Explicit incremental admission without changing historical canonical digests."""

from datetime import timedelta

import pytest
from agent_core.domain.coverage_contracts import coverage_digest
from agent_core.domain.coverage_model_budget import CoverageModelPolicy
from agent_core.domain.coverage_task_admission import CoverageTaskAdmission
from pydantic import TypeAdapter, ValidationError

from tests.agent_core.test_coverage_task_admission import NOW, admission


def test_mode_is_explicit_and_bound_without_changing_legacy_json():
    legacy = admission()
    raw = legacy.model_dump(mode="json")
    assert "validation_mode" not in raw
    assert CoverageTaskAdmission.model_validate(raw).validation_mode == "eager"
    assert (
        CoverageTaskAdmission.model_validate({**raw, "validation_mode": "eager"}).model_dump(
            mode="json"
        )
        == raw
    )
    incremental = CoverageTaskAdmission.model_validate(
        {**raw, "validation_mode": "final_certification"}
    )
    assert incremental.model_dump(mode="json")["validation_mode"] == "final_certification"
    assert coverage_digest(incremental.model_dump(mode="json")) != coverage_digest(raw)
    nested = TypeAdapter(list[CoverageTaskAdmission]).dump_python(
        [legacy, incremental], mode="json"
    )
    assert nested == [raw, incremental.model_dump(mode="json")]
    with pytest.raises(ValidationError):
        CoverageTaskAdmission.model_validate({**raw, "validation_mode": "unchecked"})


def test_policy_serialization_preserves_legacy_and_pins_new_mode():
    raw = dict(
        admission_event_digest="a" * 64,
        admission_digest="b" * 64,
        task_binding_digest="c" * 64,
        model_profile="test",
        max_calls=10,
        max_tokens=100,
        max_runtime_seconds=60,
        started_at=NOW,
        deadline=NOW + timedelta(seconds=60),
    )
    legacy = CoverageModelPolicy(**raw)
    assert "validation_mode" not in legacy.model_dump(mode="json")
    new = CoverageModelPolicy(**raw, validation_mode="final_certification")
    assert CoverageModelPolicy.model_validate(new.model_dump(mode="json")) == new
    assert coverage_digest(new.model_dump(mode="json")) != coverage_digest(
        legacy.model_dump(mode="json")
    )
