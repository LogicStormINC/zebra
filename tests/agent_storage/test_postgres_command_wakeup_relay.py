"""Fenced physical delivery ownership is not a business retry or execution lease."""

from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from datetime import timedelta
from hashlib import sha256
from uuid import uuid4

import psycopg
import pytest
from agent_storage.postgres.command_wakeup import _canonical_json
from agent_storage.postgres.command_wakeup_relay import claim_relay_batch, settle_relay_claim
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb

from tests.agent_storage.test_command_wakeup import _command
from tests.agent_storage.test_postgres_command_wakeup import NAMESPACE, _enable, _seed, _store
from tests.agent_storage.test_postgres_command_wakeup import dsn as _dsn_fixture
from tests.agent_storage.test_postgres_command_wakeup import postgres_dsn as _postgres_dsn_fixture
from tests.agent_storage.test_postgres_lease_clock import _wait, _wait_locked, _worker_dsn

dsn = _dsn_fixture
postgres_dsn = _postgres_dsn_fixture


def _seed_outbox(dsn, count=1):
    session = _seed(dsn)
    _enable(dsn)
    for n in range(count):
        _store(dsn).append(_command(session.session_id, sequence=3+n, key=str(n)))


def _claim(dsn, owner="relay-a", **kwargs):
    return claim_relay_batch(dsn, deployment_namespace=NAMESPACE, owner=owner, **kwargs)


def _rows(dsn):
    with psycopg.connect(dsn, row_factory=dict_row) as connection:
        return connection.execute("SELECT * FROM broker_outbox ORDER BY message_id").fetchall()


def _expire_claim(dsn):
    with psycopg.connect(dsn) as connection:
        connection.execute("UPDATE broker_outbox SET lease_expires_at = clock_timestamp()")


@pytest.mark.parametrize("batch", [0, -1, True, 33, 1.0])
def test_relay_bound_rejected_before_db(batch):
    with pytest.raises(ValueError, match="batch"):
        _claim("not-a-dsn", batch_size=batch)


def test_concurrent_claims_disjoint_and_skip_locked(dsn):
    _seed_outbox(dsn, 4)
    with psycopg.connect(dsn) as blocker:
        blocked = blocker.execute(
            "SELECT message_id FROM broker_outbox ORDER BY message_id LIMIT 1 FOR UPDATE"
        ).fetchone()[0]
        with ThreadPoolExecutor(max_workers=2) as executor:
            a = executor.submit(_claim, dsn, "a", batch_size=2)
            b = executor.submit(_claim, dsn, "b", batch_size=2)
            claims = (*a.result(timeout=5), *b.result(timeout=5))
        assert len(claims) == 3
        assert len({claim.message_id for claim in claims}) == 3
        assert blocked not in {claim.message_id for claim in claims}
    assert len(_claim(dsn)) == 1
    assert _claim(dsn) == ()


def test_lost_confirmation_reclaims_identical_physical_message(dsn):
    _seed_outbox(dsn)
    first, = _claim(dsn)
    _expire_claim(dsn)
    second, = _claim(dsn, "relay-b")
    assert second.body == first.body and second.message_id == first.message_id
    assert second.fence == first.fence + 1 and second.publish_attempt == 2
    assert not settle_relay_claim(dsn, first, confirmed=True)
    assert not settle_relay_claim(dsn, replace(second, owner="foreign"), confirmed=True)
    assert settle_relay_claim(dsn, second, confirmed=True)
    assert not settle_relay_claim(dsn, second, confirmed=True)
    assert _rows(dsn)[0]["status"] == "published"
    assert _claim(dsn) == ()


def test_retry_backoff_and_deployment_isolation(dsn):
    _seed_outbox(dsn)
    assert claim_relay_batch(dsn, deployment_namespace="other", owner="test") == ()
    first, = _claim(dsn)
    assert settle_relay_claim(dsn, first, confirmed=False)
    row, = _rows(dsn)
    assert row["status"] == "pending" and row["last_error_code"] == "publish_unconfirmed"
    assert row["published_at"] is None
    assert _claim(dsn) == ()
    with psycopg.connect(dsn) as connection:
        connection.execute("UPDATE broker_outbox SET available_at = clock_timestamp(), "
                           "publish_attempts = 100")
    second, = _claim(dsn)
    assert second.body == first.body
    assert settle_relay_claim(dsn, second, confirmed=False)
    with psycopg.connect(dsn) as connection:
        delay = connection.execute(
            "SELECT extract(epoch FROM available_at-clock_timestamp()) FROM broker_outbox"
        ).fetchone()[0]
    assert 59 < delay <= 60


@pytest.mark.parametrize("column,value", [
    ("envelope_digest", "0" * 64), ("scope_key", "wrong"),
    ("message_id", uuid4()), ("aggregate_id", uuid4()), ("operation_id", uuid4()),
    ("message_type", "wrong"), ("wake_generation", 1),
])
def test_duplicated_identity_corruption_is_dead_without_payload_error(dsn, column, value):
    _seed_outbox(dsn)
    with psycopg.connect(dsn) as connection:
        connection.execute(psycopg.sql.SQL("UPDATE broker_outbox SET {} = %s").format(
            psycopg.sql.Identifier(column)), (value,))
    assert _claim(dsn) == ()
    row, = _rows(dsn)
    assert row["status"] == "dead" and row["last_error_code"] == "invalid_outbox"


def test_frozen_scope_corruption_fails_closed(dsn):
    _seed_outbox(dsn)
    with psycopg.connect(dsn) as connection:
        connection.execute("UPDATE session_projections SET namespace_id = 'foreign'")
    assert _claim(dsn) == ()
    assert _rows(dsn)[0]["status"] == "dead"


@pytest.mark.parametrize("field,value", [
    ("correlation_id", str(uuid4())), ("accepted_sequence", 99),
    ("idempotency_key", "forged"),
])
def test_valid_shape_rehashed_body_still_requires_canonical_event(dsn, field, value):
    _seed_outbox(dsn)
    row, = _rows(dsn)
    body = {**row["envelope_json"], field: value}
    digest = sha256(_canonical_json(body).encode()).hexdigest()
    with psycopg.connect(dsn) as connection:
        connection.execute("UPDATE broker_outbox SET envelope_json = %s, envelope_digest = %s",
                           (Jsonb(body), digest))
    assert _claim(dsn) == ()
    assert _rows(dsn)[0]["last_error_code"] == "invalid_outbox"


@pytest.mark.parametrize("confirmed", [True, False])
def test_settlement_after_unchanged_row_wait_cannot_resurrect_expired_claim(dsn, confirmed):
    _seed_outbox(dsn)
    claim, = _claim(dsn, ttl=timedelta(seconds=2))
    name = f"settle-{uuid4()}"
    with ThreadPoolExecutor(max_workers=1) as executor:
        with psycopg.connect(dsn, autocommit=True) as observer:
            with psycopg.connect(dsn) as blocker:
                blocker.execute("SELECT message_id FROM broker_outbox FOR UPDATE").fetchall()
                result = executor.submit(settle_relay_claim, _worker_dsn(dsn, name), claim,
                                         confirmed=confirmed)
                _wait_locked(observer, name)
                assert observer.execute("SELECT clock_timestamp() < %s",
                                        (claim.lease_expires_at,)).fetchone()[0]
                _wait(observer, "SELECT clock_timestamp() > %s", (claim.lease_expires_at,))
            assert result.result(timeout=3) is False
    row, = _rows(dsn)
    assert row["status"] == "publishing" and row["published_at"] is None
    assert row["lease_expires_at"] == claim.lease_expires_at
