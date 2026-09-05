"""Exact cancelled-fence cleanup accounting, without any engine IO."""

from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from uuid import uuid4

import psycopg
import pytest
from agent_storage.postgres.command_runtime_cleanup import (
    claim_runtime_cleanup,
    settle_runtime_cleanup,
)
from agent_storage.postgres.command_wakeup_control import handle_control_command

from tests.agent_storage.test_command_wakeup import _command
from tests.agent_storage.test_postgres_command_wakeup import NAMESPACE, _seed, _store
from tests.agent_storage.test_postgres_command_wakeup import dsn as _dsn_fixture
from tests.agent_storage.test_postgres_command_wakeup import postgres_dsn as _pg_fixture
from tests.agent_storage.test_postgres_command_wakeup_control import _intent
from tests.agent_storage.test_postgres_command_wakeup_discovery import SCOPE
from tests.agent_storage.test_postgres_lease_clock import _wait, _wait_locked, _worker_dsn
from tests.agent_storage.test_postgres_runtime_instances import _instances, _setup

dsn = _dsn_fixture
postgres_dsn = _pg_fixture


def _prepare_cleanup(dsn, *, created=True):
    with psycopg.connect(dsn) as connection:
        existing = connection.execute(
            "SELECT 1 FROM control_plane_epochs WHERE deployment_namespace=%s", (NAMESPACE,)
        ).fetchone()
    event = None
    if existing:
        # Reuse this test's established epoch/rollout, never bootstrap it twice.
        session = _seed(dsn)
        event = _store(dsn).append(_command(session.session_id, key=str(uuid4())))
    lease = _setup(dsn, event=event)
    instances = _instances(dsn, lease)
    instance = str(uuid4())
    instances.reserve(instance, str(lease.session_id), "d" * 64)
    if created:
        instances.created(instance, "b" * 64)
    command = _intent(dsn, lease.session_id, "cancel")
    handle_control_command(
        dsn, deployment_namespace=NAMESPACE, scope=SCOPE, accepted_event_id=command.event_id
    )
    return instance, command


def _claim(dsn, **kwargs):
    return claim_runtime_cleanup(
        dsn,
        deployment_namespace=NAMESPACE,
        owner=kwargs.pop("owner", "cleanup"),
        engine_identity=kwargs.pop("engine_identity", "a" * 64),
        **kwargs,
    )


def _rows(dsn):
    with psycopg.connect(dsn) as connection:
        obligation = connection.execute(
            "SELECT status,error_code FROM command_runtime_cleanup ORDER BY created_at"
        ).fetchall()
        instances = connection.execute(
            "SELECT status,container_id FROM runtime_instances ORDER BY created_at"
        ).fetchall()
    return obligation, instances


def _due(dsn):
    with psycopg.connect(dsn) as connection:
        connection.execute("UPDATE command_runtime_cleanup SET available_at=clock_timestamp()")


def test_exact_cleanup_settlement_and_duplicate_are_fenced(dsn):
    _prepare_cleanup(dsn)
    claim = _claim(dsn)
    assert claim.target is not None
    assert dict(claim.target.labels)["zebra.agent.fence"] == "1"
    assert settle_runtime_cleanup(dsn, claim, removed_container_id="b" * 64)
    assert _rows(dsn) == ([("done", None)], [("removed", "b" * 64)])
    assert not settle_runtime_cleanup(dsn, claim, removed_container_id="b" * 64)
    assert _claim(dsn) is None


def test_unsettled_provisioning_then_exact_discovery_and_cleanup(dsn):
    _prepare_cleanup(dsn, created=False)
    claim = _claim(dsn)
    assert claim.target.container_id is None
    assert settle_runtime_cleanup(dsn, claim, error_code="creation_unsettled")
    assert _rows(dsn) == ([("pending", "creation_unsettled")], [("provisioning", None)])
    _due(dsn)
    claim = _claim(dsn)
    assert settle_runtime_cleanup(dsn, claim, removed_container_id="c" * 64)
    assert _rows(dsn) == ([("done", None)], [("removed", "c" * 64)])


@pytest.mark.parametrize(
    "column,value",
    [
        ("tenant_id", "victim"),
        ("workspace_id", "victim"),
        ("authority_issuer", "https://victim.example"),
    ],
)
def test_scope_conflict_does_not_remove_or_falsely_complete(dsn, column, value):
    _prepare_cleanup(dsn)
    with psycopg.connect(dsn) as connection:
        connection.execute(
            psycopg.sql.SQL("UPDATE runtime_instances SET {}=%s").format(
                psycopg.sql.Identifier(column)
            ),
            (value,),
        )
    claim = _claim(dsn)
    assert claim.target is None
    assert _rows(dsn) == (
        [("requires_reconciliation", "invalid_control_evidence")],
        [("created", "b" * 64)],
    )


def test_other_engine_stays_pending_not_done(dsn):
    _prepare_cleanup(dsn)
    claim = _claim(dsn, engine_identity="c" * 64)
    assert claim.target is None
    assert _rows(dsn)[0] == [("pending", "engine_unavailable")]
    assert not settle_runtime_cleanup(dsn, claim)


def test_missing_revoked_fence_requires_reconciliation(dsn):
    _prepare_cleanup(dsn)
    with psycopg.connect(dsn) as connection:
        connection.execute("UPDATE command_control_receipts SET revoked_token=NULL")
    assert _claim(dsn).target is None
    assert _rows(dsn)[0] == [("requires_reconciliation", "missing_revoked_fence")]


def test_stale_claim_cannot_settle_after_takeover(dsn):
    _prepare_cleanup(dsn)
    first = _claim(dsn)
    with psycopg.connect(dsn) as connection:
        connection.execute("UPDATE command_runtime_cleanup SET lease_expires_at=clock_timestamp()")
    second = _claim(dsn, owner="successor")
    assert second.fence > first.fence
    assert not settle_runtime_cleanup(dsn, first, removed_container_id="b" * 64)
    assert settle_runtime_cleanup(dsn, second, removed_container_id="b" * 64)


def test_settlement_instance_lock_wait_counts_toward_claim_expiry(dsn):
    _prepare_cleanup(dsn)
    claim = _claim(dsn, ttl=timedelta(seconds=1))
    name = f"cleanup-wait-{uuid4()}"
    with psycopg.connect(dsn, autocommit=True) as observer:
        with psycopg.connect(dsn) as blocker, ThreadPoolExecutor(max_workers=1) as pool:
            blocker.execute("SELECT * FROM runtime_instances FOR UPDATE").fetchall()
            future = pool.submit(
                settle_runtime_cleanup, _worker_dsn(dsn, name), claim, removed_container_id="b" * 64
            )
            try:
                _wait_locked(observer, name)
                _wait(
                    observer,
                    "SELECT clock_timestamp()>lease_expires_at FROM command_runtime_cleanup",
                    (),
                )
            finally:
                blocker.commit()
            assert future.result(timeout=5) is False
    assert _rows(dsn)[1] == [("created", "b" * 64)]


def test_busy_session_deferral_advances_to_healthy_next_candidate(dsn):
    _, first = _prepare_cleanup(dsn)
    _, second = _prepare_cleanup(dsn)
    with psycopg.connect(dsn) as blocker, ThreadPoolExecutor(max_workers=1) as pool:
        blocker.execute(
            "SELECT pg_advisory_xact_lock(hashtextextended(%s,0))",
            (f"{NAMESPACE}:{first.session_id}",),
        )
        deferred = pool.submit(_claim, dsn).result(timeout=3)
        assert deferred.accepted_event_id == first.event_id and not deferred.leased
        healthy = pool.submit(_claim, dsn).result(timeout=3)
        assert healthy.accepted_event_id == second.event_id and healthy.leased
        blocker.commit()
    assert settle_runtime_cleanup(dsn, healthy, removed_container_id="b" * 64)


@pytest.mark.parametrize("reason", ["poison", "attempts", "age"])
def test_poison_or_exhausted_first_obligation_does_not_starve_next(dsn, reason):
    _, first = _prepare_cleanup(dsn)
    _, second = _prepare_cleanup(dsn)
    with psycopg.connect(dsn) as connection:
        if reason == "poison":
            connection.execute(
                "UPDATE command_control_receipts SET revoked_owner=NULL WHERE accepted_event_id=%s",
                (first.event_id,),
            )
        elif reason == "attempts":
            connection.execute(
                "UPDATE command_runtime_cleanup SET attempts=32 WHERE accepted_event_id=%s",
                (first.event_id,),
            )
        else:
            connection.execute(
                "UPDATE command_runtime_cleanup SET created_at=clock_timestamp()-"
                "interval '2 days' WHERE accepted_event_id=%s",
                (first.event_id,),
            )
    assert not _claim(dsn).leased
    healthy = _claim(dsn)
    assert healthy.accepted_event_id == second.event_id
    assert settle_runtime_cleanup(dsn, healthy, removed_container_id="b" * 64)
    assert _rows(dsn)[0][0][0] == "requires_reconciliation"


@pytest.mark.parametrize("error", [None, "creation_unsettled"])
def test_late_created_id_between_claim_and_settlement_is_safe(dsn, error):
    instance, _ = _prepare_cleanup(dsn, created=False)
    claim = _claim(dsn)
    with psycopg.connect(dsn) as connection:
        connection.execute(
            "UPDATE runtime_instances SET container_id=%s,status='created' WHERE instance_id=%s",
            ("b" * 64, instance),
        )
    assert settle_runtime_cleanup(
        dsn, claim, removed_container_id="b" * 64 if error is None else None, error_code=error
    )
    expected = "done" if error is None else "pending"
    assert _rows(dsn)[0][0][0] == expected


def test_newer_fence_instance_is_preserved_and_not_treated_as_revoked(dsn):
    _prepare_cleanup(dsn)
    with psycopg.connect(dsn) as connection:
        connection.execute("UPDATE runtime_instances SET fencing_token=fencing_token+1")
    claim = _claim(dsn)
    assert claim.leased and claim.target is None
    assert settle_runtime_cleanup(dsn, claim)
    assert _rows(dsn) == ([("done", None)], [("created", "b" * 64)])


def test_success_resets_consecutive_retry_budget(dsn):
    _prepare_cleanup(dsn)
    with psycopg.connect(dsn) as connection:
        connection.execute("UPDATE command_runtime_cleanup SET attempts=31")
    claim = _claim(dsn)
    assert claim.leased
    assert settle_runtime_cleanup(dsn, claim, removed_container_id="b" * 64)
    with psycopg.connect(dsn) as connection:
        assert connection.execute("SELECT attempts FROM command_runtime_cleanup").fetchone() == (0,)
