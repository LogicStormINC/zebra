"""Native certification phases remain independent after certificate append."""
# ruff: noqa: F811

from contextlib import contextmanager

import pytest
from agent_core.domain.coverage_contracts import CoverageRefusalReason, CoverageRefusedError
from agent_storage.postgres import coverage_publication as publication
from agent_storage.postgres.coverage_artifacts import read_artifact

from tests.agent_storage.test_postgres_command_wakeup import dsn, postgres_dsn  # noqa: F401
from tests.worker.coverage_model_cloud_fixtures import model_cloud  # noqa: F401
from tests.worker.test_coverage_model_acceptance import accepted, certify, report_for


@pytest.mark.parametrize("damage", [None, "object", "authority"])
def test_native_post_append_phase_is_fresh_and_failure_rolls_back(model_cloud, monkeypatch, damage):
    env = model_cloud
    _, observation, merge, _ = accepted(env)
    ref, digest = report_for(env, (observation, merge))
    phases = []
    scope = env.cloud._locked_proof_scope

    @contextmanager
    def traced_scope(*args, **kwargs):
        assert kwargs["final_certification"] is True
        with scope(*args, **kwargs) as reader:
            assert reader is not env.cloud
            phases.append(reader)
            yield reader

    monkeypatch.setattr(env.cloud, "_locked_proof_scope", traced_scope)
    project = publication.project_watermark
    appended, corrupted_read = False, False

    def after_append(*args, **kwargs):
        nonlocal appended
        assert phases and phases[-1]._proof_connection is None
        project(*args, **kwargs)
        appended = True
        if damage == "object":
            def corrupt(*_, **__):
                nonlocal corrupted_read
                corrupted_read = True
                raise ValueError("original object corrupted after append")
            monkeypatch.setattr(env.objects, "read_version_verified", corrupt)
        elif damage == "authority":
            env.wire.revoked = True

    monkeypatch.setattr(publication, "project_watermark", after_append)
    if damage is None:
        certify(env, ref, digest)
        assert len(phases) == 2 and phases[0] is not phases[1]
    elif damage == "object":
        with pytest.raises(ValueError, match="original object corrupted after append"):
            certify(env, ref, digest)
        assert corrupted_read and len(phases) == 2
    else:
        with pytest.raises(CoverageRefusedError) as failure:
            certify(env, ref, digest)
        assert failure.value.reason is CoverageRefusalReason.AUTHORITY_INVALID
    assert appended
    assert all(reader._proof_connection is None and not reader._proof_records for reader in phases)
    with env.database.connect() as connection:
        count = connection.execute(
            "SELECT count(*) AS n FROM session_events WHERE event_type='coverage_report_certified'"
        ).fetchone()["n"]
    assert count == (damage is None)
    with pytest.raises(RuntimeError, match="ended"):
        read_artifact(phases[0], ref, digest, env.session)


def test_native_revocation_during_pure_proof_read_rolls_back_certification(
    model_cloud, monkeypatch,
):
    env = model_cloud
    _, observation, merge, _ = accepted(env)
    ref, digest = report_for(env, (observation, merge))
    scope, original = env.cloud._locked_proof_scope, env.objects.read_version_verified
    read_revoked = False

    def revoked_read(*args):
        nonlocal read_revoked
        body = original(*args)
        read_revoked = env.wire.revoked = True
        return body

    @contextmanager
    def revoking_scope(*args, **kwargs):
        with scope(*args, **kwargs) as reader:
            with monkeypatch.context() as patch:
                patch.setattr(env.objects, "read_version_verified", revoked_read)
                yield reader

    monkeypatch.setattr(env.cloud, "_locked_proof_scope", revoking_scope)
    with pytest.raises(CoverageRefusedError) as failure:
        certify(env, ref, digest)
    assert failure.value.reason is CoverageRefusalReason.AUTHORITY_INVALID and read_revoked
    with env.database.connect() as connection:
        assert connection.execute(
            "SELECT count(*) AS n FROM session_events WHERE event_type='coverage_report_certified'"
        ).fetchone()["n"] == 0
