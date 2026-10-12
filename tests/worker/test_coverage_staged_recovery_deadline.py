"""Transient original-version timeout defers recovery rather than failing its batch."""

from datetime import UTC, datetime, timedelta
from time import monotonic
from types import SimpleNamespace

import pytest
from agent_storage.postgres.coverage_recovery_preparation import CoverageRecoveryDeferred
from zebra_agent_worker.coverage_staged_recovery import revalidate_uploaded_responses


def test_staged_original_finalizer_timeout_is_deferred():
    record = SimpleNamespace(
        artifact_id="exact-original",
        reservation=SimpleNamespace(retained_until=datetime.now(UTC) + timedelta(minutes=1)),
    )
    receipt = SimpleNamespace(expectation="exact-expectation", object_version="version")

    def timeout(*args):
        raise TimeoutError("provider transport deadline")

    source = SimpleNamespace(
        _record=lambda identifier: record,
        objects=SimpleNamespace(read_version_verified_before=timeout),
    )
    with pytest.raises(CoverageRecoveryDeferred):
        revalidate_uploaded_responses(
            source, [(record, receipt, b"digest")], lambda: None, monotonic() + 5,
        )
