"""Long full-suite collection cannot age a new Worker's synthetic snapshot."""

from datetime import UTC, datetime, timedelta

import pytest
from agent_core.domain.coverage_contracts import CoverageRefusedError

from tests.agent_integrations import test_coverage_snapshot as fixture
from tests.agent_integrations.test_coverage_snapshot_preparation import setup_source
from tests.worker.test_coverage_bootstrap import inputs


@pytest.mark.parametrize("v2", [False, True])
def test_live_worker_fixture_uses_its_creation_clock(monkeypatch, v2):
    monkeypatch.setattr(fixture, "NOW", datetime.now(UTC) - timedelta(days=2))
    env = inputs(v2=v2)
    prepared = env.source.create(
        env.admission.contract, authority=env.host, idempotency_key="clock"
    )
    assert prepared.descriptor.as_of <= datetime.now(UTC) < prepared.descriptor.expires_at


def test_expired_fixture_snapshot_is_still_refused():
    now = datetime.now(UTC)
    source, _, _ = setup_source(now=lambda: now - timedelta(hours=1))
    # A live authority must not rescue a genuinely expired snapshot.
    authority = fixture.AUTHORITY.model_copy(update={"expires_at": now + timedelta(hours=1)})
    source.host.now = lambda: now
    with pytest.raises(CoverageRefusedError, match="snapshot_expired"):
        source.create(fixture.CONTRACT, authority=authority, idempotency_key="expired")
