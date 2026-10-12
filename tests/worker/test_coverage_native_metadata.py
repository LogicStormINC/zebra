"""Actual Worker reads couple fresh authority and full metadata, not permissions."""
# ruff: noqa: F401,F811

from dataclasses import replace
from uuid import UUID

import psycopg
import pytest
from agent_core.domain.sessions import SessionStatus
from zebra_agent_config.coverage_settings import CoverageWorkSettings
from zebra_agent_worker.coverage_native_executor import NativeCoverageExecutor

from tests.worker.coverage_model_cloud_fixtures import dsn, model_cloud, postgres_dsn
from tests.worker.test_coverage_dispatch import native_handoff, native_worker


@pytest.mark.parametrize("native_worker", ["first_create"], indirect=True)
@pytest.mark.parametrize("model_cloud", [{"validation_mode": "final_certification"}], indirect=True)
def test_native_record_read_owns_one_fresh_authority_metadata_statement(native_worker, monkeypatch):
    import zebra_agent_worker.coverage_dispatch as dispatch

    env, checked = native_worker, False
    env.service._settings = replace(
        env.service._settings, coverage_work=CoverageWorkSettings(max_milliseconds=60000),
    )
    original = psycopg.Connection.execute

    def compose(**kwargs):
        nonlocal checked
        run, statements = NativeCoverageExecutor(**kwargs), []
        identifier = UUID(run.binding.snapshot.manifest_artifact_ref.removeprefix("artifact://"))

        def traced(connection, query, *args, **kw):
            statements.append(str(query))
            return original(connection, query, *args, **kw)

        with monkeypatch.context() as patch:
            patch.setattr(psycopg.Connection, "execute", traced)
            record = run.artifacts._record(identifier)
        business = [query for query in statements if query.lower() != "discard all"]
        assert record is not None and record.artifact_id == identifier
        assert len(business) == 1
        assert "artifact_payload_metadata" in business[0] and "snapshot_json" in business[0]
        assert "FOR SHARE" not in business[0]
        # A foreign callback must not produce an authority-qualified snapshot.
        assert callable(getattr(run.artifacts, "_metadata_reader", None))
        with monkeypatch.context() as patch:
            patch.setattr(run.artifacts, "_metadata_reader", lambda *_: pytest.fail("foreign read"))
            assert run.artifacts._record(identifier) == record
        checked = True
        return run

    monkeypatch.setattr(dispatch, "NativeCoverageExecutor", compose)
    handoff = native_handoff(env)
    result = env.service.execute_claimed_session(handoff.lease, lease_ttl_seconds=300)
    assert checked and result.session.status is SessionStatus.COMPLETED
