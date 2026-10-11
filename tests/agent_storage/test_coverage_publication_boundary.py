"""Final certificate-read authority and clock checks against isolated PostgreSQL."""

from datetime import UTC, datetime, timedelta

import psycopg
import pytest
from agent_core.domain.coverage_contracts import CoverageRefusalReason, CoverageRefusedError

from tests.agent_storage.test_coverage_publication import (
    _certify,
    _prepare_publication,
    _read,
    cloud_publication,  # noqa: F401 - imported pytest fixture
    publication,  # noqa: F401 - imported pytest fixture
)
from tests.agent_storage.test_postgres_command_wakeup import postgres_dsn  # noqa: F401
from tests.agent_storage.test_postgres_coverage import dsn, source_counts  # noqa: F401
from tests.agent_storage.test_postgres_coverage import env as postgres_env  # noqa: F401


def test_revoked_during_final_lifecycle_scan_refuses_certificate_read(
    cloud_publication, monkeypatch,  # noqa: F811 - imported pytest fixture
):
    env = cloud_publication
    _certify(env)
    before = source_counts(env)
    original = env.store._check_publication_lifecycle
    revoked = False
    scans = checks = 0

    def revoke_after_scan(*args):
        nonlocal revoked, scans
        original(*args)
        scans += 1
        revoked = True

    def check_authority():
        nonlocal checks
        checks += 1
        if revoked:
            raise CoverageRefusedError(CoverageRefusalReason.AUTHORITY_INVALID)

    monkeypatch.setattr(env.store, "_check_publication_lifecycle", revoke_after_scan)
    with pytest.raises(CoverageRefusedError, match="authority_invalid"):
        _read(env, check_authority=check_authority)
    assert scans == 1 and checks == 3
    assert source_counts(env) == before


def test_snapshot_expiry_during_final_authority_callback_refuses_certificate_read(
    postgres_env,  # noqa: F811 - imported pytest fixture
):
    env = postgres_env
    expires = datetime.now(UTC) + timedelta(seconds=3)
    env.binding = env.binding.model_copy(update={"snapshot": env.binding.snapshot.model_copy(
        update={"expires_at": expires},
    )})
    # Reuse the existing fixture preparation, including co-located Cloud metadata.
    env = cloud_publication.__wrapped__(_prepare_publication(env))
    _certify(env)
    env.leases.release(env.session.session_id, fence=env.fence)
    before = source_counts(env)
    checks = 0

    def check_authority():
        nonlocal checks
        checks += 1
        if checks == 3:
            with psycopg.connect(env.dsn) as connection:
                connection.execute(
                    """SELECT pg_sleep(GREATEST(0,
                       EXTRACT(EPOCH FROM %s::timestamptz-clock_timestamp()))+0.05)""",
                    (expires,),
                )

    with pytest.raises(ValueError, match="expired"):
        _read(env, check_authority=check_authority)
    assert checks == 3
    assert source_counts(env) == before
