"""Actual Worker evidence owner releases its SQL unit before Host descriptor I/O."""
# ruff: noqa: F401,F811 - imported pytest fixtures

import sys
from dataclasses import replace
from types import FunctionType

import pytest
from agent_core.domain.coverage_contracts import CoverageRefusalReason, CoverageRefusedError
from agent_core.domain.events import EventType
from agent_core.domain.sessions import SessionStatus
from agent_storage.postgres.coverage_evidence_operation import PostgresCoverageEvidenceOperation
from agent_storage.postgres.work_unit import borrow_work_unit
from zebra_agent_config.coverage_settings import CoverageWorkSettings

from tests.worker.coverage_model_cloud_fixtures import NAMESPACE, dsn, model_cloud, postgres_dsn
from tests.worker.test_coverage_dispatch import native_handoff, native_worker
from tests.worker.test_coverage_effect import SignedHost


@pytest.mark.parametrize("native_worker", ["first_create"], indirect=True)
@pytest.mark.parametrize("model_cloud", [{"validation_mode": "final_certification"}], indirect=True)
@pytest.mark.parametrize("ack", ["normal", "revoked_after_commit", "cloned_local_callback"])
def test_actual_worker_evidence_host_descriptor_never_borrows_transaction(
    native_worker, monkeypatch, ack,
):
    env = native_worker
    env.service._settings = replace(
        env.service._settings, coverage_work=CoverageWorkSettings(max_milliseconds=60000),
    )
    active, owners, host_units, refused, replaced = [], [], [], [], []
    execute = PostgresCoverageEvidenceOperation._execute.__code__
    previous = sys.getprofile()
    request = SignedHost.request

    def host(self, *args, **kwargs):
        if active:
            unit = borrow_work_unit((env.dsn, NAMESPACE))
            host_units.append(unit)
            if (ack == "revoked_after_commit" and unit is None
                    and active[-1].f_locals.get("receipt") is not None
                    and "result" in active[-1].f_locals):
                with env.database.connect() as connection:
                    binding = active[-1].f_locals["binding"]
                    usage = connection.execute(
                        "SELECT receipt FROM coverage_model_calls WHERE deployment_namespace=%s "
                        "AND namespace=%s AND run_id=%s AND receipt IS NOT NULL",
                        (NAMESPACE, binding.namespace, binding.run_id),
                    ).fetchall()
                assert len(usage) == 1, "Host postcommit guard preceded durable usage"
                refused.append(True)
                raise CoverageRefusedError(CoverageRefusalReason.AUTHORITY_INVALID)
        return request(self, *args, **kwargs)

    def observe(frame, event, result):
        if frame.f_code is execute:
            if event == "call":
                active.append(frame)
                owner = frame.f_locals["self"]
                owners.append(owner)
                if ack == "cloned_local_callback":
                    local = owner.check_local_authority
                    index = local.__code__.co_freevars.index("check_local_native")
                    callback = local.__closure__[index].cell_contents
                    clone = FunctionType(callback.__code__, callback.__globals__,
                                         callback.__name__, closure=callback.__closure__)
                    assert clone.__code__ is callback.__code__ and clone is not callback
                    local.__closure__[index].cell_contents = clone
                    replaced.append(True)
            elif event == "return":
                active.remove(frame)
        if previous is not None:
            previous(frame, event, result)

    monkeypatch.setattr(SignedHost, "request", host)
    handoff = native_handoff(env)
    sys.setprofile(observe)
    try:
        result = env.service.execute_claimed_session(handoff.lease, lease_ttl_seconds=300)
    finally:
        sys.setprofile(previous)
    if ack == "normal":
        assert result.session.status is SessionStatus.COMPLETED
        assert len(owners) == 3 and not refused
    elif ack == "revoked_after_commit":
        assert result.session.status is SessionStatus.FAILED and refused == [True]
        events = env.events.list_for_session(env.session)
        assert any(event.event_type is EventType.COVERAGE_MODEL_USAGE_RECORDED for event in events)
        assert not any(event.event_type is EventType.COVERAGE_REPORT_CERTIFIED for event in events)
        assert len([request for request in env.native_requests
                    if request.url.path == "/chat/completions"]) == 1
    else:
        assert result.session.status is SessionStatus.FAILED and replaced == [True]
        assert not host_units, "altered capture reached physical Host I/O"
        assert not any(event.event_type is EventType.COVERAGE_MODEL_USAGE_RECORDED
                       for event in env.events.list_for_session(env.session))
    if ack != "cloned_local_callback":
        assert host_units
    assert all(unit is None for unit in host_units), "Host descriptor I/O borrowed evidence TX"
    assert all(owner.check_local_authority is owner.store._artifacts.check_local_authority
               for owner in owners)
