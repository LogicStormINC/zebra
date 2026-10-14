"""Native checkpoint boundaries; pure checks complement the actual Worker/PG cases."""

from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from agent_core.domain.coverage_contracts import coverage_digest
from agent_storage.postgres.command_wakeup_recovery_proof import (
    coverage_generation_usage,
    verified_coverage_recovery,
)

from tests.worker.test_coverage_dispatch import (  # noqa: F401
    dsn,
    model_cloud,
    native_handoff,
    native_worker,
    postgres_dsn,
)


class Connection:
    def __init__(self):
        self.now = datetime.now(UTC)
        self.revision = 10
        self.started = {"sequence": 7, "event_type": "harness_attempt_started"}
        self.approvals = []
        self.prefix_counts = {}
        self.queries = []
        self.history_bytes = 100

    def execute(self, sql, params=None):
        self.queries.append(sql)
        if "command_recovery_attempts" in sql:
            self.rows = [row | {"history_count": len(self.approvals),
                                "history_bytes": self.history_bytes}
                         for row in self.approvals]
        elif "result_count" in sql:
            self.rows = [{"watermark": mark, "count": self.prefix_counts[mark]}
                         for mark in params[-1]]
        elif "clock_timestamp()" in sql:
            self.row = {"now": self.now}
        elif "current_version" in sql:
            self.row = {"current_version": self.revision}
        elif "event_type" in sql:
            self.row = self.started
        else:
            raise AssertionError("unexpected native proof query")
        return self

    def fetchone(self):
        return self.row

    def fetchall(self):
        return self.rows


@pytest.fixture
def boundary():
    connection = Connection()
    pending = {
        "scope_key": "scope",
        "command_id": uuid4(),
        "session_id": uuid4(),
        "accepted_event_id": uuid4(),
        "accepted_sequence": 4,
        "current_generation": 0,
    }
    receipt = {
        **{k: pending[k] for k in ("scope_key", "command_id", "session_id", "accepted_event_id")},
        "status": "accepted",
        "handled_event_id": None,
        "started_event_id": uuid4(),
        "execution_floor_sequence": 5,
        "wake_generation": 0,
    }

    def check(conn, namespace, row, previous):
        assert conn is connection and namespace == "fixture" and row is pending
        return {
            "session_id": str(row["session_id"]),
            "accepted_event_id": str(row["accepted_event_id"]),
            "generation": previous["wake_generation"],
            "floor": previous["execution_floor_sequence"],
            "stream_revision": conn.revision,
            "receipt_digest": coverage_digest(
                {
                    k: v if v is None or isinstance(v, str | int) else str(v)
                    for k, v in previous.items()
                }
            ),
            "valid_until": (conn.now + timedelta(seconds=10)).isoformat(),
        }

    return connection, pending, receipt, check


def verify(boundary, check=None):
    connection, pending, receipt, configured = boundary
    return verified_coverage_recovery(connection, "fixture", pending, receipt, check or configured)


def test_exact_current_and_next_generation_boundary_are_verified_again(boundary):
    first = verify(boundary)
    boundary[1]["current_generation"] = 1
    assert verify(boundary) == first


@pytest.mark.parametrize(
    "field,value",
    [
        ("status", "requires_reconciliation"),
        ("handled_event_id", "unknown"),
        ("execution_floor_sequence", None),
        ("execution_floor_sequence", 3),
        ("scope_key", "other"),
        ("command_id", "other"),
        ("session_id", "other"),
        ("accepted_event_id", "other"),
        ("wake_generation", 4),
    ],
)
def test_foreign_or_uncertain_receipt_cannot_invoke_configured_proof(boundary, field, value):
    boundary[2][field] = value
    reached = []
    with pytest.raises(ValueError):
        verify(boundary, lambda *args: reached.append(True))
    assert reached == []


def test_missing_configured_native_proof_is_not_a_recovery_bypass(boundary):
    connection, pending, receipt, _ = boundary
    with pytest.raises(ValueError):
        verified_coverage_recovery(connection, "fixture", pending, receipt, None)


@pytest.mark.parametrize(
    "started",
    [
        None,
        {"sequence": 5, "event_type": "harness_attempt_started"},
        {"sequence": 11, "event_type": "harness_attempt_started"},
        {"sequence": 7, "event_type": "model_call_requested"},
    ],
)
def test_missing_or_wrong_started_event_is_not_safe_execution_evidence(boundary, started):
    boundary[0].started = started
    with pytest.raises(ValueError):
        verify(boundary)


@pytest.mark.parametrize(
    "field",
    ["session_id", "accepted_event_id", "generation", "floor", "stream_revision", "receipt_digest"],
)
def test_configured_proof_cannot_rebind_native_command_fields(boundary, field):
    configured = boundary[3]

    def forged(*args):
        return configured(*args) | {field: "wrong"}

    with pytest.raises(ValueError):
        verify(boundary, forged)


def test_final_database_clock_refuses_expiry_during_native_proof(boundary):
    configured = boundary[3]

    def delayed(*args):
        proof = configured(*args)
        boundary[0].now += timedelta(seconds=11)
        return proof

    with pytest.raises(ValueError, match="expired before final native clock"):
        verify(boundary, delayed)


def test_command_age_crossing_final_clock_is_not_renewed_by_new_generation(boundary):
    conn, pending, _, configured = boundary
    pending["created_at"] = conn.now - timedelta(hours=24) + timedelta(seconds=1)

    def delayed(*args):
        proof = configured(*args)
        conn.now += timedelta(seconds=2)
        return proof

    with pytest.raises(ValueError, match="expired before final native clock"):
        verify(boundary, delayed)


@pytest.fixture
def progress_history(boundary):
    conn, pending, receipt, check = boundary
    pending["current_generation"] = 6
    proof = check(conn, "fixture", pending, receipt) | {
        "run_id": "run",
        "namespace": "coverage",
        "task_binding_digest": "b" * 64,
        "source_watermark": 30,
        "expected_count": 12,
        "expected_digest": "a" * 64,
        "accepted_count": 7,
    }
    for index in range(1, 7):
        conn.approvals.append(
            {
                "wake_generation": index,
                "reason": "coverage_continuation",
                "approved_stream_sequence": index + 10,
                "coverage_proof": proof
                | {
                    "generation": index - 1,
                    "stream_revision": index + 10,
                    "source_watermark": index + 10,
                    "accepted_count": index,
                },
            }
        )
        conn.prefix_counts[index + 10] = index
    return conn, pending, proof


def audit(progress_history):
    conn, pending, proof = progress_history
    return coverage_generation_usage(conn, "fixture", pending, proof, maximum_crashes=5)


def test_more_than_five_proven_progress_wakes_spend_no_crash_allowance(progress_history):
    assert audit(progress_history) == (0, 6)
    assert len(progress_history[0].queries) == 2
    for row in progress_history[0].approvals[:5]:
        row["reason"] = "coverage_checkpoint"
    assert audit(progress_history) == (5, 6)
    progress_history[0].approvals[-1]["reason"] = "coverage_checkpoint"
    with pytest.raises(ValueError, match="crash allowance"):
        audit(progress_history)


@pytest.mark.parametrize("generations", [0, 1, 6, 64, 1000])
def test_generation_query_count_is_bounded_not_one_per_generation(progress_history, generations):
    conn, pending, proof = progress_history
    pending["current_generation"] = generations
    proof.update(expected_count=generations + 2, accepted_count=generations + 1,
                 source_watermark=generations + 10)
    template = conn.approvals[0]
    conn.approvals = [template | {
        "wake_generation": index,
        "approved_stream_sequence": index + 10,
        "coverage_proof": proof | {
            "generation": index - 1, "stream_revision": index + 10,
            "source_watermark": index + 10, "accepted_count": index,
        },
    } for index in range(1, generations + 1)]
    conn.prefix_counts = {index + 10: index for index in range(1, generations + 1)}
    assert audit(progress_history) == (0, generations)
    assert len(conn.queries) == (2 if generations else 1)


def test_repeated_watermark_cannot_claim_different_counts(progress_history):
    conn, _, _ = progress_history
    conn.approvals[-1]["coverage_proof"]["source_watermark"] = 15
    with pytest.raises(ValueError, match="no new canonical"):
        audit(progress_history)


def test_repeated_crash_watermark_keeps_one_exact_native_prefix(progress_history):
    conn, _, _ = progress_history
    conn.approvals[-1]["reason"] = "coverage_checkpoint"
    conn.approvals[-1]["coverage_proof"].update(source_watermark=15, accepted_count=5)
    assert audit(progress_history) == (1, 5)
    assert len(conn.queries) == 2


def test_generation_history_keeps_native_volume_bound(progress_history):
    progress_history[0].history_bytes = 32 * 1024 * 1024 + 1
    with pytest.raises(ValueError, match="exceeds bounds"):
        audit(progress_history)


@pytest.mark.parametrize(
    "damage",
    [
        "missing",
        "gap",
        "expected",
        "namespace",
        "count",
        "no_progress",
        "source",
        "unproved",
        "watermark_bool",
        "watermark_negative",
        "watermark_future",
    ],
)
def test_generation_audit_refuses_forged_or_nonprogress_approvals(progress_history, damage):
    conn, _, _ = progress_history
    row = conn.approvals[-1]
    if damage == "missing":
        conn.approvals.pop()
    elif damage == "gap":
        row["wake_generation"] += 1
    elif damage == "expected":
        row["coverage_proof"]["expected_digest"] = "c" * 64
    elif damage == "namespace":
        row["coverage_proof"]["namespace"] = "other"
    elif damage == "count":
        row["coverage_proof"]["accepted_count"] = True
    elif damage == "no_progress":
        row["coverage_proof"]["accepted_count"] = 5
        conn.prefix_counts[row["coverage_proof"]["source_watermark"]] = 5
    elif damage == "source":
        conn.prefix_counts[row["coverage_proof"]["source_watermark"]] = 0
    elif damage.startswith("watermark_"):
        row["coverage_proof"]["source_watermark"] = {
            "watermark_bool": True, "watermark_negative": -1, "watermark_future": 31,
        }[damage]
    else:
        row["coverage_proof"] = None
    with pytest.raises(ValueError):
        audit(progress_history)


def native_snapshot(env):
    """No raw payloads or credentials in assertion failures."""
    with env.database.connect() as conn:
        return {
            table: conn.execute(f"SELECT count(*) AS n FROM {table}").fetchone()["n"]
            for table in (
                "session_events",
                "coverage_units",
                "coverage_model_calls",
                "command_recovery_attempts",
                "broker_outbox",
                "broker_command_inbox",
            )
        } | {
            "command_fingerprints": {
                table: conn.execute(
                    "SELECT md5(coalesce(jsonb_agg(to_jsonb(t) "
                    "ORDER BY to_jsonb(t)::text)::text,'[]')) AS digest "
                    f"FROM {table} t"
                ).fetchone()["digest"]
                for table in (
                    "session_command_pending",
                    "command_handoff_receipts",
                    "command_recovery_attempts",
                    "broker_outbox",
                )
            },
            "pending": conn.execute(
                "SELECT current_generation,status FROM session_command_pending"
            ).fetchone(),
            "ledger": conn.execute(
                "SELECT calls,charged_tokens,unresolved FROM coverage_model_ledger"
            ).fetchall(),
            "lease": conn.execute("SELECT fencing_token FROM worker_leases").fetchall(),
        }


@pytest.mark.parametrize("damage", ["calls", "witness", "source", "missing_verifier"])
def test_native_continuation_handoff_rechecks_proof_before_new_lease(
    native_worker,  # noqa: F811
    damage,
):
    from agent_storage.postgres.command_wakeup_handoff import HandoffStatus

    env = native_worker
    first = native_handoff(env)
    assert first.status is HandoffStatus.ACCEPTED
    env.service.execute_claimed_session(first.lease, lease_ttl_seconds=300)
    with env.database.connect() as conn:
        if damage == "calls":
            assert conn.execute("DELETE FROM coverage_model_calls RETURNING 1").fetchall()
        elif damage == "witness":
            assert conn.execute("DELETE FROM coverage_model_events RETURNING 1").fetchall()
    if damage == "source":
        env.wire.revoked = True
    before = native_snapshot(env)
    result = native_handoff(env, checker=damage != "missing_verifier")
    assert result.status is HandoffStatus.REQUIRES_RECONCILIATION and result.lease is None
    assert native_snapshot(env) == before
    assert sum(r.url.path == "/chat/completions" for r in env.native_requests) == 1


def test_native_unknown_model_attempt_is_quarantined_without_second_http(native_worker):  # noqa: F811
    from agent_storage.postgres.command_wakeup_handoff import HandoffStatus
    from agent_storage.postgres.command_wakeup_recovery import RecoveryStatus, recover_command_batch

    from tests.worker.coverage_model_cloud_fixtures import NAMESPACE

    class ProcessCrash(BaseException):
        pass

    env = native_worker
    env.reply = ProcessCrash()
    first = native_handoff(env)
    assert first.status is HandoffStatus.ACCEPTED
    with pytest.raises(ProcessCrash):
        env.service.execute_claimed_session(first.lease, lease_ttl_seconds=300)
    with env.database.connect() as conn:
        ledger = conn.execute(
            "SELECT calls,charged_tokens,unresolved FROM coverage_model_ledger"
        ).fetchone()
        assert ledger["calls"] == ledger["unresolved"] == 1
        conn.execute("UPDATE session_command_pending SET recovery_due_at=clock_timestamp()")
        conn.execute("UPDATE broker_outbox SET status='published',published_at=clock_timestamp()")

    def check(conn, ns, pending, receipt):
        return env.service._coverage_runtime.recovery_check(env.service, conn, ns, pending, receipt)

    results = recover_command_batch(
        env.dsn,
        deployment_namespace=NAMESPACE,
        scope=env.scope,
        coverage_check=check,
    )
    assert len(results) == 1 and results[0].status is RecoveryStatus.REQUIRES_RECONCILIATION
    with env.database.connect() as conn:
        assert (
            conn.execute(
                "SELECT calls,charged_tokens,unresolved FROM coverage_model_ledger"
            ).fetchone()
            == ledger
        )
        assert not conn.execute("SELECT 1 FROM command_recovery_attempts").fetchall()
    assert sum(r.url.path == "/chat/completions" for r in env.native_requests) == 1


def test_native_recovery_proves_accepted_batch_after_crash_before_atomic_wake(
    native_worker,  # noqa: F811
    monkeypatch,
):
    import zebra_agent_worker.coverage_dispatch as dispatch
    from agent_core.domain.events import EventType
    from agent_core.domain.sessions import SessionStatus
    from agent_storage.postgres.command_wakeup_handoff import HandoffStatus
    from agent_storage.postgres.command_wakeup_recovery import RecoveryStatus, recover_command_batch

    from tests.worker.coverage_model_cloud_fixtures import NAMESPACE

    class ProcessCrash(BaseException):
        pass

    reached = []

    def crash(*args):
        reached.append(True)
        raise ProcessCrash()

    env = native_worker
    first = native_handoff(env)
    assert first.status is HandoffStatus.ACCEPTED
    with monkeypatch.context() as patch:
        patch.setattr(dispatch, "continue_coverage_command", crash)
        with pytest.raises(ProcessCrash):
            env.service.execute_claimed_session(first.lease, lease_ttl_seconds=300)
    assert reached == [True]
    assert (
        sum(
            e.event_type is EventType.COVERAGE_BATCH_ACCEPTED
            for e in env.events.list_for_session(env.session)
        )
        == 1
    )
    with env.database.connect() as conn:
        assert not conn.execute("SELECT 1 FROM command_recovery_attempts").fetchall()
        conn.execute("UPDATE session_command_pending SET recovery_due_at=clock_timestamp()")
        conn.execute("UPDATE broker_outbox SET status='published',published_at=clock_timestamp()")

    def check(conn, ns, pending, receipt):
        return env.service._coverage_runtime.recovery_check(env.service, conn, ns, pending, receipt)

    results = recover_command_batch(
        env.dsn, deployment_namespace=NAMESPACE, scope=env.scope, coverage_check=check
    )
    assert len(results) == 1 and results[0].status is RecoveryStatus.APPROVED
    with env.database.connect() as conn:
        assert conn.execute("SELECT reason FROM command_recovery_attempts").fetchone() == {
            "reason": "coverage_checkpoint"
        }
    second = native_handoff(env)
    assert second.status is HandoffStatus.ACCEPTED
    completed = env.service.execute_claimed_session(second.lease, lease_ttl_seconds=300)
    assert completed.session.status is SessionStatus.COMPLETED
    assert sum(r.url.path == "/chat/completions" for r in env.native_requests) == 1
    assert (
        sum(
            e.event_type is EventType.COVERAGE_REPORT_CERTIFIED
            for e in env.events.list_for_session(env.session)
        )
        == 1
    )


def test_native_issued_report_crash_recovers_after_original_deadline_without_model(
    native_worker,  # noqa: F811
    monkeypatch,
):
    import zebra_agent_worker.coverage_dispatch as dispatch
    import zebra_agent_worker.coverage_recovery_authority as recovery
    from agent_core.domain.events import EventType
    from agent_core.domain.sessions import SessionStatus
    from agent_storage.postgres.command_wakeup_handoff import HandoffStatus
    from agent_storage.postgres.command_wakeup_recovery import RecoveryStatus, recover_command_batch

    from tests.worker.coverage_model_cloud_fixtures import NAMESPACE

    class ProcessCrash(BaseException):
        pass

    reached = []

    def crash(*args):
        reached.append(True)
        raise ProcessCrash()

    env = native_worker
    first = native_handoff(env)
    assert first.status is HandoffStatus.ACCEPTED
    env.service.execute_claimed_session(first.lease, lease_ttl_seconds=300)
    second = native_handoff(env)
    assert second.status is HandoffStatus.ACCEPTED
    with monkeypatch.context() as patch:
        patch.setattr(dispatch, "finish_certified_execution", crash)
        with pytest.raises(ProcessCrash):
            env.service.execute_claimed_session(second.lease, lease_ttl_seconds=300)
    assert reached == [True]
    issued = [
        e
        for e in env.events.list_for_session(env.session)
        if e.event_type is EventType.COVERAGE_REPORT_CERTIFIED
    ]
    assert len(issued) == 1
    requests_before = len(env.native_requests)
    with env.database.connect() as conn:
        conn.execute("UPDATE session_command_pending SET recovery_due_at=clock_timestamp()")
        conn.execute("UPDATE broker_outbox SET status='published',published_at=clock_timestamp()")

    class HistoricalReadClock(datetime):
        @classmethod
        def now(cls, tz=None):
            return datetime.now(tz) + timedelta(seconds=env.admission.max_runtime_seconds + 1)

    monkeypatch.setattr(dispatch, "datetime", HistoricalReadClock)
    monkeypatch.setattr(recovery, "datetime", HistoricalReadClock)

    def check(conn, ns, pending, receipt):
        return env.service._coverage_runtime.recovery_check(env.service, conn, ns, pending, receipt)

    results = recover_command_batch(
        env.dsn, deployment_namespace=NAMESPACE, scope=env.scope, coverage_check=check
    )
    assert len(results) == 1 and results[0].status is RecoveryStatus.APPROVED
    third = native_handoff(env)
    assert third.status is HandoffStatus.ACCEPTED
    completed = env.service.execute_claimed_session(third.lease, lease_ttl_seconds=300)
    assert completed.session.status is SessionStatus.COMPLETED
    assert sum(r.url.path == "/chat/completions" for r in env.native_requests) == 1
    assert not any(r.url.host == "api.deepseek.com" for r in env.native_requests[requests_before:])
    assert [
        e
        for e in env.events.list_for_session(env.session)
        if e.event_type is EventType.COVERAGE_REPORT_CERTIFIED
    ] == issued
