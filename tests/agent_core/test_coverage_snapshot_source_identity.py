"""Local snapshot provenance is additive; legacy canonical identities stay intact."""

import pytest
from agent_core.domain.coverage_snapshot import CoverageSnapshot

from tests.agent_core.test_coverage_contracts import records, snapshot


def test_legacy_snapshot_omits_unknown_source_in_canonical_serialization():
    value = snapshot(records())
    legacy = value.model_dump(mode="json")
    assert value.source_resource_ref is None and "source_resource_ref" not in legacy
    assert CoverageSnapshot.model_validate(legacy) == value
    assert value.model_copy(update={"source_resource_ref": None}).model_dump(mode="json") == legacy


@pytest.mark.parametrize("value", ["", " ", " history", "history ", True, 1])
def test_source_resource_requires_an_explicit_valid_name(value):
    with pytest.raises(ValueError):
        CoverageSnapshot.model_validate(
            {**snapshot(records()).model_dump(), "source_resource_ref": value}
        )


def test_verified_source_is_frozen_and_round_trips():
    value = CoverageSnapshot.model_validate(
        {**snapshot(records()).model_dump(), "source_resource_ref": "history"}
    )
    assert CoverageSnapshot.model_validate_json(value.model_dump_json()) == value
    with pytest.raises(ValueError):
        value.source_resource_ref = "foreign"
