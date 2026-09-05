"""Actual PostgreSQL scoped rollout and side-effect-free shadow evidence."""

from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from hashlib import sha256

import psycopg
import pytest
from agent_core.contracts.broker_envelope import PrincipalScope, parse_broker_envelope
from agent_storage.postgres.command_rollout import (
    get_command_scope_mode,
    set_command_scope_rollout,
)
from agent_storage.postgres.command_rollout_shadow import (
    ShadowClaim,
    claim_command_shadow_batch,
    command_shadow_reconciliation,
    observe_command_shadow,
    reject_command_shadow,
    settle_command_shadow,
)
from agent_storage.postgres.command_wakeup import command_scope_key
from agent_storage.postgres.command_wakeup_handoff import HandoffStatus, handoff_command
from agent_storage.postgres.command_wakeup_pickup import discover_command_pickups
from agent_storage.postgres.command_wakeup_relay import claim_relay_batch
from psycopg.rows import dict_row

from tests.agent_storage.test_command_wakeup import _command
from tests.agent_storage.test_postgres_command_wakeup import NAMESPACE, _enable, _seed, _store
from tests.agent_storage.test_postgres_command_wakeup import dsn as _dsn_fixture
from tests.agent_storage.test_postgres_command_wakeup import postgres_dsn as _pg_fixture

dsn = _dsn_fixture
postgres_dsn = _pg_fixture


def _scope(tenant: str) -> PrincipalScope:
    return PrincipalScope(kind="principal", tenant_id=tenant, workspace_id="workspace-a")


def _set(dsn: str, tenant: str, mode: str | None) -> None:
    set_command_scope_rollout(
        dsn,
        deployment_namespace=NAMESPACE,
        scope_key=command_scope_key(_scope(tenant)),
        mode=mode,
        actor="operator",
        reason="bounded rollout acceptance",
    )


def _rows(dsn: str, table: str):
    with psycopg.connect(dsn, row_factory=dict_row) as connection:
        return connection.execute(f"SELECT * FROM {table}").fetchall()


def test_scope_rollout_is_default_off_audited_and_individually_reversible(dsn):
    key = command_scope_key(_scope("tenant-a"))
    assert get_command_scope_mode(dsn, deployment_namespace=NAMESPACE, scope_key=key) == "fallback"
    _set(dsn, "tenant-a", "shadow")
    assert get_command_scope_mode(dsn, deployment_namespace=NAMESPACE, scope_key=key) == "shadow"
    row = _rows(dsn, "command_delivery_scope_rollouts")[0]
    assert (row["actor"], row["reason"]) == ("operator", "bounded rollout acceptance")
    _set(dsn, "tenant-a", None)
    assert get_command_scope_mode(dsn, deployment_namespace=NAMESPACE, scope_key=key) == "fallback"
    audit = _rows(dsn, "command_delivery_scope_rollout_audit")
    assert [(row["previous_mode"], row["new_mode"]) for row in audit] == [
        (None, "shadow"),
        ("shadow", None),
    ]


@pytest.mark.parametrize("value", ["", "z" * 64, "0" * 63])
def test_scope_rollout_rejects_unbounded_or_nonopaque_keys_without_database(value):
    with pytest.raises(ValueError):
        set_command_scope_rollout(
            "unused",
            deployment_namespace=NAMESPACE,
            scope_key=value,
            mode="broker",
            actor="operator",
            reason="test",
        )


def test_formal_relay_and_fallback_scanner_share_the_same_scope_boundary(dsn):
    sessions = {
        tenant: _seed(dsn, tenant=tenant) for tenant in ("tenant-a", "tenant-b", "tenant-c")
    }
    _enable(dsn)
    _set(dsn, "tenant-a", "broker")
    _set(dsn, "tenant-b", "shadow")
    events = {
        tenant: _store(dsn).append(_command(session.session_id, key=tenant))
        for tenant, session in sessions.items()
    }
    claims = claim_relay_batch(
        dsn,
        deployment_namespace=NAMESPACE,
        owner="relay",
        scope_mode="broker",
    )
    assert len(claims) == 1
    assert parse_broker_envelope(claims[0].body).accepted_event_id == str(
        events["tenant-a"].event_id
    )
    fallback = discover_command_pickups(
        dsn, deployment_namespace=NAMESPACE, lane="execution", scope_mode="fallback"
    )
    assert {row.accepted_event_id for row in fallback} == {
        events["tenant-b"].event_id,
        events["tenant-c"].event_id,
    }
    default_off = discover_command_pickups(
        dsn, deployment_namespace=NAMESPACE, lane="execution", scope_mode="all"
    )
    assert {row.accepted_event_id for row in default_off} == {
        event.event_id for event in events.values()
    }


def test_shadow_lane_is_bounded_separate_idempotent_and_message_id_reconciled(dsn):
    first = _seed(dsn, tenant="tenant-a")
    second = _seed(dsn, tenant="tenant-b")
    _enable(dsn)
    _set(dsn, "tenant-a", "shadow")
    _set(dsn, "tenant-b", "shadow")
    with psycopg.connect(dsn) as connection:
        connection.execute(
            """UPDATE command_wakeup_rollouts SET max_unpublished_shadow=1
               WHERE deployment_namespace=%s""",
            (NAMESPACE,),
        )
    first_event = _store(dsn).append(_command(first.session_id, key="first"))
    second_event = _store(dsn).append(_command(second.session_id, key="second"))
    assert first_event and second_event
    assert len(_rows(dsn, "broker_outbox")) == 2
    shadow_rows = _rows(dsn, "command_shadow_outbox")
    assert len(shadow_rows) == 1
    assert not _rows(dsn, "broker_command_inbox")
    assert not _rows(dsn, "worker_leases")

    claim = claim_command_shadow_batch(
        dsn, deployment_namespace=NAMESPACE, owner="shadow-relay", batch_size=1
    )[0]
    assert claim.body
    assert sha256(claim.body).hexdigest() == shadow_rows[0]["envelope_digest"]
    assert settle_command_shadow(dsn, claim, confirmed=True)
    assert observe_command_shadow(dsn, deployment_namespace=NAMESPACE, body=claim.body)
    assert not observe_command_shadow(dsn, deployment_namespace=NAMESPACE, body=claim.body)
    assert command_shadow_reconciliation(dsn, deployment_namespace=NAMESPACE) == {
        "eligible": 2,
        "mirrored": 1,
        "published": 1,
        "observed": 1,
    }
    with psycopg.connect(dsn) as connection:
        connection.execute(
            "UPDATE command_shadow_observations SET envelope_digest=%s",
            ("0" * 64,),
        )
    assert command_shadow_reconciliation(dsn, deployment_namespace=NAMESPACE) == {
        "eligible": 2,
        "mirrored": 1,
        "published": 1,
        "observed": 0,
    }
    with psycopg.connect(dsn) as connection:
        connection.execute(
            "UPDATE command_shadow_outbox SET envelope_digest=%s",
            ("1" * 64,),
        )
    assert command_shadow_reconciliation(dsn, deployment_namespace=NAMESPACE) == {
        "eligible": 2,
        "mirrored": 0,
        "published": 0,
        "observed": 0,
    }
    assert not _rows(dsn, "broker_command_inbox")
    assert not _rows(dsn, "command_handoff_receipts")
    assert not _rows(dsn, "worker_leases")


def test_busy_shadow_lock_never_blocks_formal_admission(dsn):
    session = _seed(dsn, tenant="tenant-a")
    _enable(dsn)
    _set(dsn, "tenant-a", "shadow")
    with psycopg.connect(dsn) as blocker:
        blocker.execute(
            "SELECT pg_advisory_xact_lock(hashtextextended(%s,50))",
            (f"{NAMESPACE}:command-shadow",),
        )
        event = _store(dsn).append(_command(session.session_id, key="lock-proof"))
        assert event is not None
        assert len(_rows(dsn, "broker_outbox")) == 1
        assert not _rows(dsn, "command_shadow_outbox")
    assert command_shadow_reconciliation(dsn, deployment_namespace=NAMESPACE) == {
        "eligible": 1,
        "mirrored": 0,
        "published": 0,
        "observed": 0,
    }


def test_mode_flip_is_rechecked_inside_handoff_scope_lock(dsn):
    session = _seed(dsn, tenant="tenant-a")
    _enable(dsn)
    _set(dsn, "tenant-a", "broker")
    event = _store(dsn).append(_command(session.session_id, key="flip-proof"))
    key = command_scope_key(_scope("tenant-a"))
    with psycopg.connect(dsn) as blocker, ThreadPoolExecutor(1) as pool:
        blocker.execute(
            "SELECT pg_advisory_xact_lock(hashtextextended(%s,50))",
            (f"{NAMESPACE}:command-rollout:{key}",),
        )
        pending = pool.submit(
            handoff_command,
            dsn,
            deployment_namespace=NAMESPACE,
            scope=_scope("tenant-a"),
            accepted_event_id=event.event_id,
            owner_instance_id="broker-worker",
            ttl=timedelta(seconds=30),
            required_scope_mode="broker",
        )
        blocker.execute(
            """UPDATE command_delivery_scope_rollouts SET mode='shadow'
               WHERE deployment_namespace=%s AND scope_key=%s""",
            (NAMESPACE, key),
        )
        blocker.commit()
        result = pending.result(2)
    assert result.status is HandoffStatus.SCOPE_DEFERRED
    assert not _rows(dsn, "worker_leases")
    assert not _rows(dsn, "broker_command_inbox")


def test_shadow_settlement_rejects_forged_claim_identity(dsn):
    session = _seed(dsn, tenant="tenant-a")
    _enable(dsn)
    _set(dsn, "tenant-a", "shadow")
    _store(dsn).append(_command(session.session_id, key="first"))
    claim = claim_command_shadow_batch(
        dsn, deployment_namespace=NAMESPACE, owner="shadow-relay", batch_size=1
    )[0]
    forged = ShadowClaim(
        claim.deployment_namespace,
        claim.shadow_message_id,
        claim.source_message_id,
        claim.owner,
        claim.fence,
        claim.body + b" ",
    )
    assert not settle_command_shadow(dsn, forged, confirmed=True)
    assert settle_command_shadow(dsn, claim, confirmed=True)


def test_corrupt_shadow_source_is_dead_without_blocking_later_claim(dsn):
    sessions = [_seed(dsn, tenant=tenant) for tenant in ("tenant-a", "tenant-b")]
    _enable(dsn)
    for tenant in ("tenant-a", "tenant-b"):
        _set(dsn, tenant, "shadow")
    for index, session in enumerate(sessions):
        _store(dsn).append(_command(session.session_id, key=str(index)))
    shadow_rows = _rows(dsn, "command_shadow_outbox")
    with psycopg.connect(dsn) as connection:
        connection.execute(
            """UPDATE command_shadow_outbox SET envelope_digest=%s
               WHERE shadow_message_id=%s""",
            ("0" * 64, shadow_rows[0]["shadow_message_id"]),
        )
    claims = claim_command_shadow_batch(
        dsn, deployment_namespace=NAMESPACE, owner="shadow-relay", batch_size=2
    )
    assert len(claims) == 1
    assert {row["status"] for row in _rows(dsn, "command_shadow_outbox")} == {
        "dead",
        "publishing",
    }


def test_shadow_invalid_or_cross_namespace_observation_has_no_formal_side_effect(dsn):
    before = tuple(_rows(dsn, table) for table in ("broker_command_inbox", "worker_leases"))
    with pytest.raises(ValueError, match="invalid shadow"):
        observe_command_shadow(dsn, deployment_namespace=NAMESPACE, body=b"{}")
    assert reject_command_shadow(dsn, deployment_namespace=NAMESPACE, body=b"{}")
    assert not reject_command_shadow(dsn, deployment_namespace=NAMESPACE, body=b"{}")
    rejection = _rows(dsn, "command_shadow_rejections")[0]
    assert set(rejection) == {
        "deployment_namespace",
        "consumer_role",
        "body_digest",
        "rejection_code",
        "observed_at",
    }
    assert tuple(_rows(dsn, table) for table in ("broker_command_inbox", "worker_leases")) == before
