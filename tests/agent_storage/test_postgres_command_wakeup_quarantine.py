"""Actual diagnostic durability, safe metadata and fallback isolation."""

import asyncio
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from datetime import timedelta
from hashlib import sha256
from uuid import uuid4

import psycopg
import pytest
from agent_core.contracts.broker_diagnostic import parse_broker_diagnostic
from agent_runtime.command_wakeup_quarantine import CommandQuarantineError, CommandWakeupQuarantine
from agent_storage.postgres.command_wakeup_quarantine import (
    claim_rejection,
    record_rejection,
    settle_rejection,
)
from agent_storage.postgres.command_wakeup_quarantine_candidate import quarantine_candidate
from psycopg import sql
from psycopg.conninfo import make_conninfo

from tests.agent_storage.test_postgres_command_wakeup import NAMESPACE, _seed
from tests.agent_storage.test_postgres_command_wakeup import dsn as _dsn_fixture
from tests.agent_storage.test_postgres_command_wakeup import postgres_dsn as _pg_fixture
from tests.agent_storage.test_postgres_command_wakeup_control import _intent
from tests.agent_storage.test_postgres_command_wakeup_handoff import _handoff, _prepare
from tests.agent_storage.test_postgres_command_wakeup_recovery import _rows
from tests.agent_storage.test_postgres_lease_clock import _wait, _wait_locked, _worker_dsn

dsn = _dsn_fixture
postgres_dsn = _pg_fixture
ROLE = "zebra.session.command"


def _record(dsn, raw=b"synthetic-private-input", **kwargs):
    return record_rejection(
        dsn,
        deployment_namespace=NAMESPACE,
        consumer_role=ROLE,
        raw=raw,
        code=kwargs.pop("code", "invalid_broker_envelope"),
        **kwargs,
    )


def _claim(dsn, **kwargs):
    return claim_rejection(
        dsn,
        deployment_namespace=NAMESPACE,
        consumer_role=ROLE,
        owner=kwargs.pop("owner", "test-owner"),
        **kwargs,
    )


def _due(dsn):
    with psycopg.connect(dsn) as connection:
        connection.execute(
            "UPDATE command_delivery_rejections SET available_at=clock_timestamp(), "
            "lease_expires_at=clock_timestamp()-interval '1 second'"
        )


def test_concurrent_duplicate_rejection_has_stable_random_identity_and_no_raw_data(dsn):
    raw = b"Bearer synthetic-private-input accepted_event_id=victim password=secret"
    with ThreadPoolExecutor(max_workers=2) as executor:
        receipts = list(executor.map(lambda _: _record(dsn, raw), range(2)))
    assert receipts[0] == receipts[1]
    (row,) = _rows(dsn, "command_delivery_rejections")
    assert row["body_digest"] == sha256(raw).hexdigest() and row["byte_count"] == len(raw)
    assert not any(text in repr(row) for text in ("Bearer", "victim", "password", "secret"))
    claim = _claim(dsn)
    diagnostic = parse_broker_diagnostic(claim.body)
    assert diagnostic.rejection_id == str(receipts[0].rejection_id)
    assert diagnostic.body_digest == row["body_digest"]
    other = _record(dsn, raw, code="broker_hint_conflict")
    assert other.rejection_id != receipts[0].rejection_id
    assert not _rows(dsn, "session_command_pending")


def test_reclaim_and_settlement_require_exact_namespace_role_owner_fence_and_expiry(dsn):
    _record(dsn)
    original = _claim(dsn)
    assert _claim(dsn, owner="other") is None
    _due(dsn)
    successor = _claim(dsn, owner="other")
    assert successor.body == original.body and successor.rejection_id == original.rejection_id
    assert successor.fence > original.fence
    for stale in (
        original,
        replace(successor, deployment_namespace="foreign"),
        replace(successor, consumer_role="foreign"),
        replace(successor, owner="wrong"),
    ):
        assert not settle_rejection(dsn, stale, confirmed=True)
    assert settle_rejection(dsn, successor, confirmed=True)
    assert _record(dsn).published
    assert _claim(dsn) is None


def test_settlement_lock_wait_past_expiry_rejects_unchanged_claim(dsn):
    _record(dsn)
    claim = _claim(dsn, ttl=timedelta(seconds=0.5))
    name = f"quarantine-settle-{uuid4()}"
    with ThreadPoolExecutor(max_workers=1) as executor:
        with psycopg.connect(dsn, autocommit=True) as observer:
            with psycopg.connect(dsn) as blocker:
                blocker.execute("SELECT rejection_id FROM command_delivery_rejections FOR UPDATE")
                result = executor.submit(
                    settle_rejection, _worker_dsn(dsn, name), claim, confirmed=True
                )
                _wait_locked(observer, name)
                _wait(
                    observer,
                    "SELECT clock_timestamp()>lease_expires_at FROM command_delivery_rejections",
                    (),
                )
            assert result.result(timeout=3) is False
    assert _rows(dsn, "command_delivery_rejections")[0]["status"] == "publishing"


def test_lost_confirm_retry_keeps_identical_diagnostic_and_network_outside_transaction(dsn):
    bodies = []

    async def publish(body, **routing):
        assert routing == {
            "exchange": "zebra.command.diagnostic.x",
            "routing_key": "delivery.rejected.v1",
        }
        with psycopg.connect(dsn) as connection:
            connection.execute(
                "SELECT rejection_id FROM command_delivery_rejections FOR UPDATE NOWAIT"
            )
        bodies.append(body)
        if len(bodies) == 1:
            raise RuntimeError("confirmation lost")

    async def scenario():
        callback = CommandWakeupQuarantine(
            dsn, deployment_namespace=NAMESPACE, publish_confirmed=publish
        )
        with pytest.raises(CommandQuarantineError):
            await callback(b"private raw", uuid4(), "invalid_broker_envelope")
        assert not await callback.publish_once()  # bounded backoff
        _due(dsn)
        assert await callback.publish_once()
        await callback(b"private raw", uuid4(), "invalid_broker_envelope")

    asyncio.run(scenario())
    assert len(bodies) == 2 and bodies[0] == bodies[1]
    assert _rows(dsn, "command_delivery_rejections")[0]["status"] == "published"


@pytest.mark.parametrize("protected", [False, True])
def test_fallback_rechecks_poison_and_never_mutates_active_handoff(dsn, protected):
    command = _prepare(dsn)
    if protected:
        _handoff(dsn, command)
    with psycopg.connect(dsn) as connection:
        connection.execute("UPDATE session_command_pending SET command_kind='cancel'")
    before = {
        table: _rows(dsn, table)
        for table in ("session_events", "worker_leases", "command_handoff_receipts")
    }
    receipt = quarantine_candidate(
        dsn,
        deployment_namespace=NAMESPACE,
        consumer_role=ROLE,
        accepted_event_id=command.event_id,
        code="broker_hint_conflict",
    )
    assert receipt is not None
    assert _rows(dsn, "session_command_pending")[0]["status"] == (
        "pending" if protected else "dead"
    )
    assert before == {table: _rows(dsn, table) for table in before}


def test_healthy_fallback_and_raw_forged_identity_cannot_quarantine_victim(dsn):
    command = _prepare(dsn)
    before = _rows(dsn, "session_command_pending")
    assert (
        quarantine_candidate(
            dsn,
            deployment_namespace=NAMESPACE,
            consumer_role=ROLE,
            accepted_event_id=command.event_id,
            code="broker_hint_conflict",
        )
        is None
    )

    async def publish(body, **kwargs):
        assert str(command.event_id).encode() not in body

    async def scenario():
        callback = CommandWakeupQuarantine(
            dsn, deployment_namespace=NAMESPACE, publish_confirmed=publish
        )
        await callback(b"forged credential payload", command.event_id, "broker_hint_conflict")

    asyncio.run(scenario())
    assert _rows(dsn, "session_command_pending") == before
    assert not _rows(dsn, "worker_leases")


def test_fallback_receipt_failure_rolls_back_poison_isolation(dsn):
    command = _prepare(dsn)
    with psycopg.connect(dsn) as connection:
        connection.execute("UPDATE session_command_pending SET command_kind='cancel'")
        connection.execute(
            "ALTER TABLE command_delivery_rejections ADD CONSTRAINT fault CHECK(false)"
        )
    with pytest.raises(psycopg.errors.CheckViolation):
        quarantine_candidate(
            dsn,
            deployment_namespace=NAMESPACE,
            consumer_role=ROLE,
            accepted_event_id=command.event_id,
            code="broker_hint_conflict",
        )
    assert _rows(dsn, "session_command_pending")[0]["status"] == "pending"
    assert not _rows(dsn, "command_delivery_rejections")


@pytest.mark.parametrize("fault", ["outbox", "canonical"])
def test_unprovable_poison_does_not_starve_healthy_candidate_and_retries_on_wrap(
    dsn, monkeypatch, fault
):
    from agent_runtime import command_wakeup_consumer as consumer_module
    from agent_runtime.command_wakeup_consumer import CommandWakeupConsumer, PickupOutcome
    from agent_storage.postgres import command_wakeup_quarantine_candidate as candidates

    poison = _prepare(dsn)
    healthy = _intent(dsn, _seed(dsn).session_id, "run")
    with psycopg.connect(dsn) as connection:
        connection.execute(
            "UPDATE session_command_pending SET created_at=clock_timestamp() "
            "- interval '1 day' WHERE accepted_event_id=%s",
            (poison.event_id,),
        )
        if fault == "outbox":
            connection.execute(
                "DELETE FROM broker_outbox WHERE operation_id=%s", (poison.payload["command_id"],)
            )
    if fault == "canonical":
        resolve = consumer_module.resolve_command_pickup
        read = candidates.read_event_in_transaction

        def unavailable(*args, **kwargs):
            if kwargs["accepted_event_id"] == poison.event_id:
                raise ValueError("canonical Event unavailable")
            return resolve(*args, **kwargs)

        monkeypatch.setattr(consumer_module, "resolve_command_pickup", unavailable)
        monkeypatch.setattr(
            candidates,
            "read_event_in_transaction",
            lambda connection, namespace, identity: None
            if identity == poison.event_id
            else read(connection, namespace, identity),
        )

    async def publish(*args, **kwargs):
        pytest.fail("no provable diagnostic body")

    async def scenario():
        callback = CommandWakeupQuarantine(
            dsn, deployment_namespace=NAMESPACE, publish_confirmed=publish
        )
        consumer = CommandWakeupConsumer(
            dsn,
            deployment_namespace=NAMESPACE,
            owner="worker",
            execute_claimed=lambda lease: None,
            quarantine=callback,
            batch_size=2,
        )
        try:
            assert await consumer.poll("execution") == (
                PickupOutcome.DEFERRED,
                PickupOutcome.SCHEDULED,
            )
            assert await consumer.poll("execution") == ()
            assert await consumer.poll("execution") == (
                PickupOutcome.DEFERRED,
                PickupOutcome.ACKNOWLEDGED,
            )
        finally:
            await consumer.close()

    asyncio.run(scenario())
    assert not _rows(dsn, "command_delivery_rejections")
    assert _rows(dsn, "command_handoff_receipts")[0]["accepted_event_id"] == healthy.event_id


@pytest.mark.parametrize("guard", ["scope", "nonpending", "later_intent"])
def test_fallback_diagnostic_does_not_isolate_unproved_or_protected_command(dsn, guard):
    command = _prepare(dsn)
    if guard == "later_intent":
        _intent(dsn, command.session_id, "resume")
    with psycopg.connect(dsn) as connection:
        connection.execute(
            "UPDATE session_command_pending SET command_kind='cancel' WHERE accepted_event_id=%s",
            (command.event_id,),
        )
        if guard == "scope":
            connection.execute("UPDATE session_command_pending SET tenant_id='foreign'")
        elif guard == "nonpending":
            connection.execute("UPDATE session_command_pending SET status='cancelled'")
    before = _rows(dsn, "session_command_pending")
    receipt = quarantine_candidate(
        dsn,
        deployment_namespace=NAMESPACE,
        consumer_role=ROLE,
        accepted_event_id=command.event_id,
        code="broker_hint_conflict",
    )
    assert receipt is not None
    assert _rows(dsn, "session_command_pending") == before


def test_v44_to_v45_upgrade_preserves_canonical_pending_and_prior_checksums(
    postgres_dsn, monkeypatch
):
    from agent_storage.postgres import migration_runner
    from agent_storage.postgres.migrations import MIGRATIONS

    schema = f"quarantine_upgrade_{uuid4().hex}"
    with psycopg.connect(postgres_dsn) as connection:
        connection.execute(sql.SQL("CREATE SCHEMA {}").format(sql.Identifier(schema)))
    isolated = make_conninfo(postgres_dsn, options=f"-c search_path={schema}")
    try:
        with monkeypatch.context() as patch:
            patch.setattr(
                migration_runner, "MIGRATIONS", tuple(m for m in MIGRATIONS if m.version <= 44)
            )
            migration_runner.apply_postgres_migrations(isolated)
        _prepare(isolated)
        before = {
            table: _rows(isolated, table)
            for table in ("session_events", "session_command_pending", "broker_outbox")
        }
        checksums = _rows(isolated, "zebra_schema_migrations")
        with monkeypatch.context() as patch:
            patch.setattr(
                migration_runner, "MIGRATIONS", tuple(m for m in MIGRATIONS if m.version <= 45)
            )
            migration_runner.apply_postgres_migrations(isolated)
            migration_runner.apply_postgres_migrations(isolated)
        assert before == {table: _rows(isolated, table) for table in before}
        assert [
            row for row in _rows(isolated, "zebra_schema_migrations") if row["version"] <= 44
        ] == checksums
        assert not _rows(isolated, "command_delivery_rejections")
    finally:
        with psycopg.connect(postgres_dsn) as connection:
            connection.execute(sql.SQL("DROP SCHEMA {} CASCADE").format(sql.Identifier(schema)))
