"""Real PG lane discovery, frozen authority and consumer control isolation."""

import asyncio
from datetime import UTC, datetime
from threading import Event

import psycopg
import pytest
from agent_core.contracts.broker_envelope import PrincipalScope
from agent_core.contracts.session_commands import SessionCommandKind
from agent_runtime.command_wakeup_consumer import CommandWakeupConsumer, PickupOutcome
from agent_storage import PostgresLeaseStore
from agent_storage.postgres.command_wakeup import _canonical_json, command_scope_key
from agent_storage.postgres.command_wakeup_pickup import (
    MAX_FAIR_CURSOR_PAGES,
    discover_command_pickups,
    resolve_command_pickup,
)

from tests.agent_runtime.test_command_wakeup_consumer import Delivery, _wait
from tests.agent_storage.test_postgres_command_wakeup import NAMESPACE, _seed, _store
from tests.agent_storage.test_postgres_command_wakeup import dsn as _dsn_fixture
from tests.agent_storage.test_postgres_command_wakeup import postgres_dsn as _pg_fixture
from tests.agent_storage.test_postgres_command_wakeup_control import _body, _control, _intent
from tests.agent_storage.test_postgres_command_wakeup_discovery import SCOPE
from tests.agent_storage.test_postgres_command_wakeup_handoff import _prepare
from tests.agent_storage.test_postgres_command_wakeup_recovery import _rows

dsn = _dsn_fixture
postgres_dsn = _pg_fixture


def _discover(dsn, lane, **kwargs):
    return discover_command_pickups(dsn, deployment_namespace=NAMESPACE, lane=lane, **kwargs)


def test_global_keyset_finds_old_sessions_and_control_lane_ignores_run_backlog(dsn):
    first = _prepare(dsn)
    commands = [first]
    for _ in range(4):
        session = _seed(dsn)
        commands.append(_intent(dsn, session.session_id, "run"))
    control = _intent(dsn, first.session_id, "cancel")
    with psycopg.connect(dsn) as connection:
        connection.execute(
            "UPDATE session_command_pending SET created_at=%s", (datetime(2001, 1, 1, tzinfo=UTC),)
        )
    found, after = [], None
    while page := _discover(dsn, "execution", batch_size=2, after=after):
        assert len(page) <= 2
        found.extend(row.accepted_event_id for row in page)
        after = page[-1].cursor
    assert set(found) == {command.event_id for command in commands}
    assert len(found) == len(commands)
    assert [row.accepted_event_id for row in _discover(dsn, "control", batch_size=1)] == [
        control.event_id
    ]
    with psycopg.connect(dsn) as connection:
        connection.execute("SET enable_seqscan=off")
        plan = connection.execute(
            """EXPLAIN SELECT accepted_event_id FROM session_command_pending
            WHERE deployment_namespace=%s AND status='pending'
              AND command_kind IN ('cancel','stop','suspend')
            ORDER BY created_at,accepted_event_id LIMIT 1""",
            (NAMESPACE,),
        ).fetchall()
    assert "command_pending_control_pickup" in str(plan)


def test_pickup_page_round_robins_scopes_before_second_command(dsn):
    first_a = _prepare(dsn)
    second_a = _intent(dsn, first_a.session_id, "run")
    session_b = _seed(dsn, tenant="tenant-b")
    first_b = _intent(dsn, session_b.session_id, "run")
    found = _discover(dsn, "execution", batch_size=2)
    assert {row.accepted_event_id for row in found} == {first_a.event_id, first_b.event_id}
    assert second_a.event_id not in {row.accepted_event_id for row in found}


def test_fair_cursor_does_not_skip_older_second_rank_under_new_tail(dsn):
    first_a = _prepare(dsn)
    second_a = _intent(dsn, first_a.session_id, "run")
    session_b = _seed(dsn, tenant="tenant-b")
    first_b = _intent(dsn, session_b.session_id, "run")
    with psycopg.connect(dsn) as connection:
        connection.execute(
            """UPDATE session_command_pending SET created_at=CASE
               WHEN accepted_event_id=%s THEN TIMESTAMPTZ '2001-01-01 00:00:01+00'
               WHEN accepted_event_id=%s THEN TIMESTAMPTZ '2001-01-01 00:00:02+00'
               ELSE TIMESTAMPTZ '2001-01-01 00:01:40+00' END""",
            (first_a.event_id, second_a.event_id),
        )
    first_page = _discover(dsn, "execution", batch_size=2)
    assert [row.accepted_event_id for row in first_page] == [first_a.event_id, first_b.event_id]
    tail = _seed(dsn, tenant="tenant-c")
    tail_command = _intent(dsn, tail.session_id, "run")
    second_page = _discover(dsn, "execution", batch_size=2, after=first_page[-1].cursor)
    assert {row.accepted_event_id for row in second_page} == {
        second_a.event_id,
        tail_command.event_id,
    }


def test_continuous_old_scope_tail_cannot_starve_new_scope(dsn):
    first_a = _prepare(dsn)
    with psycopg.connect(dsn) as connection:
        connection.execute("UPDATE command_wakeup_rollouts SET max_pending_per_scope=100")
    second_a = _intent(dsn, first_a.session_id, "run")
    cursor = _discover(dsn, "execution", batch_size=1)[0].cursor
    page = _discover(dsn, "execution", batch_size=1, after=cursor)
    assert page[0].accepted_event_id == second_a.event_id
    cursor = page[0].cursor
    session_b = _seed(dsn, tenant="tenant-b")
    first_b = _intent(dsn, session_b.session_id, "run")
    found = set()
    for _ in range((MAX_FAIR_CURSOR_PAGES * 2) + 2):
        _intent(dsn, first_a.session_id, "run")
        page = _discover(dsn, "execution", batch_size=1, after=cursor)
        assert page
        found.add(page[0].accepted_event_id)
        cursor = page[0].cursor
        if first_b.event_id in found:
            break
    assert first_b.event_id in found


def test_prefix_probes_never_discard_forward_progress_through_large_stable_backlog(dsn):
    first = _prepare(dsn)
    commands = [first, *[_intent(dsn, first.session_id, "run") for _ in range(23)]]
    found = set()
    cursor = None
    for _ in range(len(commands) + 4):
        page = _discover(dsn, "execution", batch_size=1, after=cursor)
        assert page
        found.add(page[0].accepted_event_id)
        cursor = page[0].cursor
        if found == {command.event_id for command in commands}:
            break
    assert found == {command.event_id for command in commands}


def test_frozen_active_scope_probe_finds_scope_inserted_behind_probe_under_live_tail(dsn):
    first = _prepare(dsn)
    with psycopg.connect(dsn) as connection:
        connection.execute("UPDATE command_wakeup_rollouts SET max_pending_per_scope=100")
    baseline_key = command_scope_key(SCOPE)
    candidates = [
        PrincipalScope(kind="principal", tenant_id=f"tenant-{index}", workspace_id="workspace-a")
        for index in range(10_000)
    ]
    lower = next(scope for scope in candidates if command_scope_key(scope) < baseline_key)
    higher = next(scope for scope in candidates if command_scope_key(scope) > baseline_key)
    high_session = _seed(dsn, tenant=higher.tenant_id)
    _intent(dsn, high_session.session_id, "run")

    cursor = _discover(dsn, "execution", batch_size=1)[0].cursor
    for _ in range(MAX_FAIR_CURSOR_PAGES - 1):
        _intent(dsn, first.session_id, "run")
        page = _discover(dsn, "execution", batch_size=1, after=cursor)
        assert page
        cursor = page[0].cursor
    probe_page = _discover(dsn, "execution", batch_size=1, after=cursor)
    assert probe_page and probe_page[0].cursor.probe_scope_key is not None
    cursor = probe_page[0].cursor

    new_session = _seed(dsn, tenant=lower.tenant_id)
    new_scope_command = _intent(dsn, new_session.session_id, "run")
    found = set()
    for _ in range((MAX_FAIR_CURSOR_PAGES * 3) + 3):
        _intent(dsn, first.session_id, "run")
        page = _discover(dsn, "execution", batch_size=1, after=cursor)
        assert page
        found.add(page[0].accepted_event_id)
        cursor = page[0].cursor
        if new_scope_command.event_id in found:
            break
    assert new_scope_command.event_id in found


def test_fair_pickup_query_uses_lane_partial_index(dsn):
    command = _prepare(dsn)
    cursor = _discover(dsn, "execution", batch_size=1)[0].cursor
    with psycopg.connect(dsn) as connection:
        connection.execute("SET enable_seqscan=off")
        plan = connection.execute(
            """EXPLAIN SELECT accepted_event_id,created_at,scope_sequence
               FROM session_command_pending
               WHERE deployment_namespace=%s AND status='pending'
                 AND command_kind IN ('run','resume','message')
                 AND (scope_sequence,created_at,accepted_event_id)>(%s,%s,%s)
               ORDER BY scope_sequence,created_at,accepted_event_id LIMIT 16""",
            (
                NAMESPACE,
                cursor.scope_sequence,
                cursor.created_at,
                cursor.accepted_event_id,
            ),
        ).fetchall()
    assert command.event_id == cursor.accepted_event_id
    assert "command_pending_execution_fair_pickup" in str(plan)

    with psycopg.connect(dsn) as connection:
        connection.execute("SET enable_seqscan=off")
        head_plan = connection.execute(
            """EXPLAIN SELECT DISTINCT ON (scope_key)
                      scope_key,accepted_event_id,created_at,scope_sequence
               FROM session_command_pending
               WHERE deployment_namespace=%s AND status='pending'
                 AND command_kind IN ('run','resume','message') AND scope_key<=%s
               ORDER BY scope_key,scope_sequence,created_at,accepted_event_id LIMIT 16""",
            (NAMESPACE, "f" * 64),
        ).fetchall()
    assert "command_pending_execution_scope_head" in str(head_plan)


@pytest.mark.parametrize("kind", ["run", "resume", "message", "cancel", "stop", "suspend"])
def test_admission_lane_matches_canonical_command_and_frozen_binding(dsn, kind):
    command = _prepare(dsn, kind=kind)
    row = _rows(dsn, "session_command_pending")[0]
    assert row["command_kind"] == kind
    resolved = resolve_command_pickup(
        dsn, deployment_namespace=NAMESPACE, accepted_event_id=command.event_id
    )
    assert resolved.scope == SCOPE and resolved.kind is SessionCommandKind(kind)
    assert not discover_command_pickups(dsn, deployment_namespace="foreign", lane="execution")
    with pytest.raises(ValueError, match="missing canonical"):
        resolve_command_pickup(
            dsn, deployment_namespace="foreign", accepted_event_id=command.event_id
        )


def test_poisoned_kind_or_scope_never_becomes_execution_authority(dsn):
    command = _prepare(dsn, kind="cancel")
    before = _store(dsn).list_for_session(command.session_id)
    with psycopg.connect(dsn) as connection:
        connection.execute("UPDATE session_command_pending SET command_kind='run'")
    with pytest.raises(ValueError, match="canonical identity or kind"):
        resolve_command_pickup(
            dsn, deployment_namespace=NAMESPACE, accepted_event_id=command.event_id
        )
    assert _store(dsn).list_for_session(command.session_id) == before
    assert not _rows(dsn, "worker_leases")


def test_real_handoff_and_independent_control_pickup_while_execution_slot_is_full(dsn):
    command = _prepare(dsn)
    control = _intent(dsn, command.session_id, "cancel")
    started, release = Event(), Event()
    received = []

    def execute(lease):
        received.append(lease)
        started.set()
        assert release.wait(5)

    async def quarantine(*args):
        pytest.fail("valid commands must not be quarantined")

    async def scenario():
        consumer = CommandWakeupConsumer(
            dsn,
            deployment_namespace=NAMESPACE,
            owner="worker",
            execution_slots=1,
            execute_claimed=execute,
            quarantine=quarantine,
        )
        try:
            delivery = Delivery(_body(dsn, command))
            assert await consumer.on_delivery(delivery) is PickupOutcome.SCHEDULED
            await _wait(started)
            assert delivery.acks == 1
            assert await consumer.poll("control") == (PickupOutcome.ACKNOWLEDGED,)
            assert (
                _rows(dsn, "command_control_receipts")[0]["accepted_event_id"] == control.event_id
            )
            assert (
                PostgresLeaseStore(dsn, deployment_namespace=NAMESPACE).get(command.session_id)
                is None
            )
            assert len(received) == 1
        finally:
            release.set()
            await consumer.close()

    asyncio.run(scenario())


def test_raw_scope_never_overrides_frozen_binding(dsn):
    command = _prepare(dsn)
    body = _rows(dsn, "broker_outbox")[0]["envelope_json"]
    body["scope"]["workspace_id"] = "victim"
    quarantined = []

    async def quarantine(raw, accepted_id, code):
        quarantined.append((accepted_id, code))

    async def scenario():
        consumer = CommandWakeupConsumer(
            dsn,
            deployment_namespace=NAMESPACE,
            owner="worker",
            execute_claimed=lambda lease: pytest.fail("forged input executed"),
            quarantine=quarantine,
        )
        try:
            assert (
                await consumer.on_delivery(Delivery(_canonical_json(body).encode()))
                is PickupOutcome.QUARANTINED
            )
        finally:
            await consumer.close()

    asyncio.run(scenario())
    assert quarantined == [(command.event_id, "broker_hint_conflict")]
    assert not _rows(dsn, "worker_leases")
    assert not _rows(dsn, "command_handoff_receipts")


def test_scheduling_failure_retains_committed_handoff_and_lease_for_recovery(dsn, monkeypatch):
    command = _prepare(dsn)

    async def quarantine(*args):
        pytest.fail("scheduling failure is not invalid input")

    def fail_submit(*args, **kwargs):
        raise RuntimeError("executor unavailable")

    async def scenario():
        consumer = CommandWakeupConsumer(
            dsn,
            deployment_namespace=NAMESPACE,
            owner="worker",
            execute_claimed=lambda lease: pytest.fail("not scheduled"),
            quarantine=quarantine,
        )
        monkeypatch.setattr(consumer._execution, "submit", fail_submit)
        try:
            delivery = Delivery(_body(dsn, command))
            assert await consumer.on_delivery(delivery) is PickupOutcome.DEFERRED
            assert delivery.requeues == 1 and delivery.acks == 0
            receipt = _rows(dsn, "command_handoff_receipts")[0]
            assert receipt["status"] == "accepted" and receipt["handled_event_id"] is None
            lease = PostgresLeaseStore(dsn, deployment_namespace=NAMESPACE).get(command.session_id)
            assert lease is not None and lease.fence.fencing_token == receipt["fencing_token"]
            assert _rows(dsn, "session_command_pending")[0]["status"] == "pending"
        finally:
            await consumer.close()

    asyncio.run(scenario())


@pytest.mark.parametrize("case", ["historical", "terminal", "invalid_message"])
def test_durable_reconciliation_and_duplicate_are_acknowledged_without_execution(dsn, case):
    command = _prepare(
        dsn, historical=case == "historical", kind="message" if case == "invalid_message" else "run"
    )
    if case == "terminal":
        _control(dsn, _intent(dsn, command.session_id, "cancel"))
    before = _store(dsn).list_for_session(command.session_id)

    async def quarantine(*args):
        pytest.fail("durable handoff reconciliation must not be quarantined")

    async def scenario():
        consumer = CommandWakeupConsumer(
            dsn,
            deployment_namespace=NAMESPACE,
            owner="worker",
            execute_claimed=lambda lease: pytest.fail("reconciliation executed"),
            quarantine=quarantine,
        )
        try:
            for _ in range(2):
                delivery = Delivery(_body(dsn, command))
                assert await consumer.on_delivery(delivery) is PickupOutcome.ACKNOWLEDGED
                assert delivery.acks == 1 and delivery.requeues == 0
        finally:
            await consumer.close()

    asyncio.run(scenario())
    assert _store(dsn).list_for_session(command.session_id) == before
    assert not _rows(dsn, "worker_leases")
    assert _rows(dsn, "command_handoff_receipts")[0]["status"] == "requires_reconciliation"
    assert len(_rows(dsn, "broker_command_inbox")) == 1


@pytest.mark.parametrize("limit", [True, 0, 501])
def test_discovery_rejects_unbounded_limits_without_database(limit):
    with pytest.raises(ValueError):
        _discover("unused", "control", batch_size=limit)
