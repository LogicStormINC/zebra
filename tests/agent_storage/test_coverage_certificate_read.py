"""Governed report bytes must leave the same final gate as their certificate."""

from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import psycopg
import pytest
from agent_core.domain.coverage_contracts import CoverageRefusalReason, CoverageRefusedError

from tests.agent_storage.test_coverage_publication import (
    _certify,
    _read,
    cloud_publication,  # noqa: F401
    publication,  # noqa: F401
)
from tests.agent_storage.test_postgres_command_wakeup import postgres_dsn  # noqa: F401
from tests.agent_storage.test_postgres_coverage import dsn, source_counts  # noqa: F401
from tests.agent_storage.test_postgres_coverage import env as postgres_env  # noqa: F401


def report(env, *, now=None, check_authority=lambda: None, authority_expires_at=None):
    return env.store.certified_report(
        env.binding.namespace, env.binding.run_id,
        now=datetime.now(UTC) if now is None else now,
        check_authority=check_authority,
        authority_expires_at=authority_expires_at,
    )


def test_report_bytes_match_original_certificate_and_do_not_read_after_final_gate(
    cloud_publication, monkeypatch,  # noqa: F811
):
    env = cloud_publication
    certificate = _certify(env)
    before = source_counts(env)
    checks, reads = [], []
    original = env.artifacts.read_payload_bytes_bounded

    def authority():
        checks.append(True)

    def bounded(artifact_id, *, max_bytes):
        assert len(checks) < 3, "report must not be re-read after final authority"
        reads.append(artifact_id)
        return original(artifact_id, max_bytes=max_bytes)

    with monkeypatch.context() as patch:
        patch.setattr(env.artifacts, "read_payload_bytes_bounded", bounded)
        result = report(env, check_authority=authority)
    assert result == (certificate, env.report_artifact.uri, env.report.canonical_bytes)
    assert len(checks) == 3 and reads
    assert _read(env) == result[:2]
    assert source_counts(env) == before


def test_uncertified_report_never_returns_candidate_bytes(publication):  # noqa: F811
    env = publication
    before = source_counts(env)
    assert report(env) is None
    assert source_counts(env) == before


@pytest.mark.parametrize("revoke_on_call", [1, 2, 3])
def test_revoked_report_byte_read_refuses_without_mutation(
    cloud_publication, revoke_on_call,  # noqa: F811
):
    env = cloud_publication
    _certify(env)
    before = source_counts(env)
    checks = 0

    def authority():
        nonlocal checks
        checks += 1
        if checks == revoke_on_call:
            raise CoverageRefusedError(CoverageRefusalReason.AUTHORITY_INVALID)

    with pytest.raises(CoverageRefusedError, match="authority_invalid"):
        report(env, check_authority=authority)
    assert checks == revoke_on_call and source_counts(env) == before


def test_expired_report_byte_read_refuses_without_mutation(cloud_publication):  # noqa: F811
    env = cloud_publication
    certificate = _certify(env)
    before = source_counts(env)
    with pytest.raises(ValueError, match="expired"):
        report(env, now=certificate.expires_at)
    assert source_counts(env) == before


def test_cancelled_report_byte_read_refuses_without_mutation(cloud_publication):  # noqa: F811
    env = cloud_publication
    _certify(env)
    env.store.cancel(env.binding.namespace, env.binding.run_id, fence=env.fence)
    before = source_counts(env)
    with pytest.raises(ValueError, match="cancelled"):
        report(env)
    assert source_counts(env) == before


@pytest.mark.parametrize("deadline", [
    datetime(2026, 1, 1), datetime(2026, 1, 1, tzinfo=UTC), "invalid", 0,
])
def test_invalid_authority_deadline_refuses_before_binding_or_reads(deadline):
    from agent_storage.postgres.coverage_certificate_read import read_certified_report

    with pytest.raises(CoverageRefusedError, match="authority_invalid"):
        read_certified_report(
            SimpleNamespace(), "namespace", "run", now=datetime(2026, 1, 1, tzinfo=UTC),
            check_authority=lambda: None, authority_expires_at=deadline,
        )


def test_current_grant_expiry_during_final_check_refuses_report_bytes(
    cloud_publication,  # noqa: F811
):
    env = cloud_publication
    certificate = _certify(env)
    before = source_counts(env)
    expires = datetime.now(UTC) + timedelta(seconds=2)
    assert expires < certificate.expires_at
    checks = 0

    def authority():
        nonlocal checks
        checks += 1
        if checks == 3:
            with psycopg.connect(env.dsn) as connection:
                connection.execute(
                    """SELECT pg_sleep(GREATEST(0,
                       EXTRACT(EPOCH FROM %s::timestamptz-clock_timestamp()))+0.05)""",
                    (expires,),
                )

    with pytest.raises(CoverageRefusedError, match="authority_invalid"):
        report(env, check_authority=authority, authority_expires_at=expires)
    assert checks == 3 and source_counts(env) == before


def test_live_current_grant_preserves_certified_bytes(cloud_publication):  # noqa: F811
    env = cloud_publication
    certificate = _certify(env)
    before = source_counts(env)
    result = report(env, authority_expires_at=certificate.expires_at)
    assert result == (certificate, env.report_artifact.uri, env.report.canonical_bytes)
    assert source_counts(env) == before


@pytest.mark.parametrize("forgery", ["actor", "fence", "timestamp"])
def test_report_refuses_forged_original_certificate_event(
    cloud_publication, forgery,  # noqa: F811
):
    env = cloud_publication
    _certify(env)
    with psycopg.connect(env.dsn) as connection:
        if forgery == "actor":
            connection.execute(
                "UPDATE session_events SET actor='user' "
                "WHERE event_type='coverage_report_certified'"
            )
        elif forgery == "fence":
            connection.execute(
                "UPDATE session_events SET payload=payload-'fence' "
                "WHERE event_type='coverage_report_certified'"
            )
        else:
            connection.execute(
                "UPDATE session_events SET created_at=created_at-interval '1 hour' "
                "WHERE event_type='coverage_report_certified'"
            )
    before = source_counts(env)
    with pytest.raises(ValueError):
        report(env)
    assert source_counts(env) == before
