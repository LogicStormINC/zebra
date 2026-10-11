"""Tenant owner preflight and report proof share one non-resettable budget."""

import asyncio

from agent_storage.postgres.coverage_recovery_preparation import CoverageRecoveryDeferred
from agent_storage.postgres.database import current_postgres_deadline, postgres_deadline
from zebra_agent_api.coverage_report_http import coverage_report_response

from tests.api.test_coverage_report_http import BODY, compose, request


def test_preflight_and_reader_share_deadline(monkeypatch):
    seen = []
    adapter, _ = compose(monkeypatch)

    def preflight(*_):
        seen.append(current_postgres_deadline())

    def read(*_):
        seen.append(current_postgres_deadline())
        return None

    monkeypatch.setattr("zebra_agent_api.coverage_report_http.tenant_scope_response", preflight)
    monkeypatch.setattr("zebra_agent_api.coverage_report_read.read_coverage_report", read)
    response = asyncio.run(coverage_report_response(request(), adapter))
    assert response.status_code == 409 and seen[0] == seen[1] and seen[0] is not None
    assert current_postgres_deadline() is None


def test_preflight_exhaustion_is_transient_and_never_reads_report(monkeypatch):
    adapter, calls = compose(monkeypatch)

    def preflight(*_):
        raise CoverageRecoveryDeferred("private SQL")

    monkeypatch.setattr("zebra_agent_api.coverage_report_http.tenant_scope_response", preflight)
    response = asyncio.run(coverage_report_response(request(), adapter))
    assert response.status_code == 503 and not calls and BODY not in response.body
    assert b"private SQL" not in response.body


def test_cpu_overrun_result_is_not_delivered(monkeypatch):
    from zebra_agent_api.coverage_report_read import read_coverage_report

    clock = [100.0]

    def expired(*_):
        clock[0] = 121.0
        return (object(), "retained", BODY)

    monkeypatch.setattr("zebra_agent_api.coverage_report_read._read_coverage_report", expired)
    monkeypatch.setattr("zebra_agent_api.coverage_report_read.monotonic", lambda: clock[0])
    monkeypatch.setattr(
        "agent_storage.postgres.coverage_recovery_preparation.monotonic", lambda: clock[0]
    )
    with postgres_deadline(120.0):
        try:
            read_coverage_report(None, "", None)
        except CoverageRecoveryDeferred:
            pass
        else:
            raise AssertionError("must not deliver expired proof")
