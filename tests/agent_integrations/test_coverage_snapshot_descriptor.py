"""Publication revalidation fetches one descriptor, never the full dataset."""

from datetime import UTC, datetime, timedelta

import pytest
from agent_core.domain.coverage_contracts import CoverageRefusedError
from agent_integrations import coverage_snapshot_source as module

from tests.agent_integrations.test_coverage_snapshot import AUTHORITY, NOW
from tests.agent_integrations.test_coverage_snapshot_preparation import setup_source


def test_descriptor_only_revalidation_does_not_enumerate_or_read_parts():
    source, host, _ = setup_source((b"first", b"second"))
    descriptor = source.get_descriptor("snapshot", authority=AUTHORITY)
    assert descriptor.snapshot_id == "snapshot"
    assert descriptor.record_count == 2
    assert [call["toolName"] for call in host.calls] == ["dataset.snapshot.get"]


@pytest.mark.parametrize("expired", ["authority", "budget"])
def test_descriptor_refuses_expiry_during_validation(monkeypatch, expired):
    # The signed gateway also checks wall time; do not expire at module-import time.
    authority = AUTHORITY.model_copy(update={
        "expires_at": datetime.now(UTC) + timedelta(minutes=5),
    })
    clock = {"now": NOW, "elapsed": 0.0}
    source, host, _ = setup_source(
        authority=authority, now=lambda: clock["now"], monotonic=lambda: clock["elapsed"]
    )
    original = module.parse

    def advance_after_validation(*args, **kwargs):
        value = original(*args, **kwargs)
        if expired == "authority":
            clock["now"] = authority.expires_at
        else:
            clock["elapsed"] = 60.0
        return value

    monkeypatch.setattr(module, "parse", advance_after_validation)
    with pytest.raises(CoverageRefusedError) as refused:
        source.get_descriptor("snapshot", authority=authority)
    assert refused.value.reason.value == (
        "authority_invalid" if expired == "authority" else "budget_exceeded"
    )
    assert [call["toolName"] for call in host.calls] == ["dataset.snapshot.get"]


def test_descriptor_revalidation_preserves_current_authority_refusal():
    source, host, _ = setup_source()
    host.revoked = True
    with pytest.raises(CoverageRefusedError):
        source.get_descriptor("snapshot", authority=AUTHORITY)
    assert [call["toolName"] for call in host.calls] == ["dataset.snapshot.get"]
