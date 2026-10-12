"""Native Worker uses one producer/settlement owner while final proof stays independent."""
# ruff: noqa: F401,F811

import sys
from dataclasses import replace

import pytest
from agent_core.domain.sessions import SessionStatus
from agent_storage.postgres.coverage_evidence_operation import PostgresCoverageEvidenceOperation
from zebra_agent_config.coverage_settings import CoverageWorkSettings

from tests.worker.coverage_model_cloud_fixtures import dsn, model_cloud, postgres_dsn
from tests.worker.test_coverage_dispatch import native_handoff, native_worker


@pytest.mark.parametrize("native_worker", ["first_create"], indirect=True)
@pytest.mark.parametrize("model_cloud", [{"validation_mode": "final_certification"}], indirect=True)
def test_native_worker_settles_checkpoint_and_acceptance_in_its_evidence_owner(native_worker):
    env = native_worker
    env.service._settings = replace(
        env.service._settings, coverage_work=CoverageWorkSettings(max_milliseconds=60000),
    )
    calls = {"model": 0, "accept": 0}
    previous = sys.getprofile()
    model = PostgresCoverageEvidenceOperation.publish_model_checkpoint.__code__
    accept = PostgresCoverageEvidenceOperation.commit_evidence.__code__

    def observe(frame, event, result):
        if event == "call":
            if frame.f_code is model:
                calls["model"] += 1
            if frame.f_code is accept:
                calls["accept"] += 1
        if previous is not None:
            previous(frame, event, result)

    sys.setprofile(observe)
    try:
        handoff = native_handoff(env)
        result = env.service.execute_claimed_session(handoff.lease, lease_ttl_seconds=300)
    finally:
        sys.setprofile(previous)
    assert result.session.status is SessionStatus.COMPLETED
    assert calls == {"model": 1, "accept": 2}
