"""Prepared proof never bypasses native contents, authority, retention or lock order."""

from dataclasses import replace
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import psycopg
import pytest
from agent_storage.postgres.coverage_recovery_preparation import (
    CoverageRecoveryDeferred,
    PreparedCoverageRecovery,
    RecoveryDeadlineConnection,
    RecoveryReadSnapshot,
    _digest,
    check_prepared_recovery_clock,
    prepare_command_handoff,
    prepare_command_recovery,
    prepared_recovery_connection,
)
from psycopg.rows import dict_row

from tests.agent_storage.test_postgres_command_wakeup import dsn, postgres_dsn  # noqa: F401


class Connection:
    def __init__(self):
        self.now = datetime.now(UTC)
        self.row = {"revision": 1, "original": {"accepted": 3}}
        self.calls = []

    def execute(self, sql, params=None):
        self.calls.append((sql, params))
        if "clock_timestamp()" in sql:
            return SimpleNamespace(fetchone=lambda: {"now": self.now})
        return SimpleNamespace(fetchone=lambda: self.row.copy(), fetchall=lambda: [self.row.copy()])


@pytest.mark.parametrize("protocol,reason", [
    ("coverage-execution-receipt/2", "coverage_continuation"),
    ("coverage-execution-receipt/1", "process_crash"),
])
def test_native_pickup_refuses_unsupported_or_misclassified_protocol(protocol, reason):
    conn = Connection()
    conn.row = {"reason": reason, "coverage_proof": {"continuation_protocol": protocol}}
    check = SimpleNamespace(prepare_continuation=lambda *args: pytest.fail("must refuse"))
    with pytest.raises(ValueError, match="supported native continuation consumer"):
        prepare_command_handoff(check, conn, "fixture", "event", 1)


def test_native_pickup_initial_generation_does_not_query_approval():
    conn = Connection()
    assert prepare_command_handoff(None, conn, "fixture", "event", 0) is None
    assert not conn.calls


def test_normal_preparation_uses_explicit_continuation_method_only():
    calls = []
    def legacy(*args):
        return {}

    def normal(*args):
        return {}

    class Check:
        def prepare(self, ns, event):
            calls.append(("recovery", ns, event))
            return legacy

        def prepare_continuation(self, ns, event):
            calls.append(("continuation", ns, event))
            return normal

    assert prepare_command_recovery(Check(), "fixture", "event") is legacy
    assert prepare_command_recovery(Check(), "fixture", "event", continuation=True) is normal
    assert [call[0] for call in calls] == ["recovery", "continuation"]


def test_corrupt_marked_continuation_preparation_never_downgrades():
    class Check:
        def prepare(self, ns, event):
            pytest.fail("corrupt continuation must not fall back to recovery")

        def prepare_continuation(self, ns, event):
            raise ValueError("corrupt receipt")

    check = prepare_command_recovery(Check(), "fixture", "event", continuation=True)
    with pytest.raises(ValueError, match="could not prove"):
        check(None, "fixture", {}, {})


def test_legacy_preparer_is_retained_for_normal_work_without_opt_in():
    def legacy(*args):
        return {}
    check = SimpleNamespace(prepare=lambda ns, event: legacy)
    assert prepare_command_recovery(check, "fixture", "event", continuation=True) is legacy


def prepared(connection, final=lambda: None):
    snapshot = RecoveryReadSnapshot(connection)
    snapshot.execute("SELECT pg_advisory_xact_lock(%s)", (1,)).fetchone()
    snapshot.execute("SELECT * FROM evidence WHERE id=%s FOR UPDATE", (1,)).fetchone()
    snapshot.execute("SELECT pg_advisory_xact_lock(%s)", (2,))
    snapshot.execute("SELECT * FROM lifecycle WHERE id=%s FOR SHARE", (1,)).fetchall()
    pending, receipt = {"current_generation": 2}, {"wake_generation": 1}
    proof = {"valid_until": (connection.now + timedelta(seconds=30)).isoformat()}
    return (
        PreparedCoverageRecovery(
            "fixture",
            _digest(pending),
            _digest(receipt),
            snapshot,
            proof,
            connection.now,
            lambda deadline: final(),
        ),
        pending,
        receipt,
    )


def test_preparation_never_takes_locks_but_finalization_restores_order():
    conn = Connection()
    proof, pending, receipt = prepared(conn)
    assert len(conn.calls) == 2
    assert not any("FOR UPDATE" in sql or "FOR SHARE" in sql for sql, _ in conn.calls)
    conn.calls.clear()
    assert proof(conn, "fixture", pending, receipt) == proof.proof
    assert [sql for sql, _ in conn.calls if "advisory" in sql or "FOR " in sql] == [
        "SELECT pg_advisory_xact_lock(%s)",
        "SELECT * FROM evidence WHERE id=%s FOR UPDATE",
        "SELECT pg_advisory_xact_lock(%s)",
        "SELECT * FROM lifecycle WHERE id=%s FOR SHARE",
    ]


def test_rr_repeated_reads_reuse_bytes_but_final_reads_current_rows():
    conn = Connection()
    snapshot = RecoveryReadSnapshot(conn, reuse_reads=True)
    sql = "SELECT * FROM evidence WHERE id=%s FOR SHARE"
    row = snapshot.execute(sql, (1,)).fetchone()
    row["revision"] = 99
    assert snapshot.execute(sql, (1,)).fetchone()["revision"] == 1
    assert len(conn.calls) == 1
    conn.row["original"]["accepted"] = 4
    with pytest.raises(ValueError, match="evidence changed"):
        snapshot.revalidate(conn)
    assert len(conn.calls) == 2 and conn.calls[-1][0] == sql


def test_rr_cache_capacity_falls_back_to_database(monkeypatch):
    monkeypatch.setattr(
        "agent_storage.postgres.coverage_recovery_preparation.MAX_TRANSCRIPT_BYTES", 256
    )
    conn = Connection()
    conn.row["large"] = "x" * 1000
    snapshot = RecoveryReadSnapshot(conn, reuse_reads=True)
    for _ in range(2):
        snapshot.execute("SELECT * FROM evidence").fetchone()
    assert len(conn.calls) == 2 and not snapshot.cached_reads


def test_final_read_sets_timeout_once_and_uses_earlier_deadline(monkeypatch):
    monkeypatch.setattr(
        "agent_storage.postgres.coverage_recovery_preparation.monotonic", lambda: 100
    )
    conn = Connection()
    snapshot = RecoveryReadSnapshot(conn)
    sql = "SELECT * FROM evidence FOR SHARE"
    snapshot.execute(sql).fetchone()
    conn.calls.clear()
    snapshot.revalidate(RecoveryDeadlineConnection(conn, 101), deadline=105)
    assert len(conn.calls) == 2
    assert conn.calls[0][1] == ("1000", "1000")
    assert conn.calls[1][0] == sql


def test_unversioned_source_tamper_is_not_hidden_by_same_revision():
    conn = Connection()
    proof, pending, receipt = prepared(conn)
    conn.row["original"]["accepted"] = 4
    with pytest.raises(ValueError, match="evidence changed"):
        proof(conn, "fixture", pending, receipt)


@pytest.mark.parametrize("field", ["namespace", "pending", "receipt"])
def test_prepared_boundary_is_exact(field):
    conn = Connection()
    proof, pending, receipt = prepared(conn)
    ns = "other" if field == "namespace" else "fixture"
    if field == "pending":
        pending["current_generation"] += 1
    if field == "receipt":
        receipt["wake_generation"] += 1
    with pytest.raises(ValueError, match="boundary changed"):
        proof(conn, ns, pending, receipt)


def test_authority_revocation_is_not_replaced_by_database_digest():
    def revoked():
        raise ValueError("revoked Host authority")

    conn = Connection()
    proof, pending, receipt = prepared(conn, revoked)
    with pytest.raises(ValueError, match="revoked Host"):
        proof(conn, "fixture", pending, receipt)


@pytest.mark.parametrize("expired", [False, True])
def test_final_clock_is_after_authority_and_native_locks(expired):
    conn = Connection()

    def delay():
        conn.now += timedelta(seconds=31 if expired else 6)

    proof, pending, receipt = prepared(conn, delay)
    with pytest.raises(CoverageRecoveryDeferred, match="finalization window"):
        proof(conn, "fixture", pending, receipt)


@pytest.mark.parametrize("sql", ["UPDATE evidence SET revision=2", "DELETE FROM evidence"])
def test_preparation_refuses_mutations(sql):
    with pytest.raises(ValueError, match="only native SELECT"):
        RecoveryReadSnapshot(Connection()).execute(sql)


def test_unknown_callbacks_do_not_silently_enable_prepared_recovery():
    def legacy(*args):
        return {}

    assert prepare_command_recovery(legacy, "fixture", "event") is legacy
    assert prepare_command_recovery(None, "fixture", "event") is None


def test_preparation_failure_becomes_existing_refusal_not_execution():
    class Check:
        def prepare(self, ns, event):
            raise ValueError("private source error")

    check = prepare_command_recovery(Check(), "fixture", "event")
    with pytest.raises(ValueError, match="could not prove"):
        check(Connection(), "fixture", {}, {})


def test_final_transaction_clock_rechecks_age_after_writes():
    conn = Connection()
    proof, pending, receipt = prepared(conn)
    proof(conn, "fixture", pending, receipt)
    conn.now += timedelta(seconds=6)
    with pytest.raises(CoverageRecoveryDeferred, match="finalization window"):
        check_prepared_recovery_clock(conn, proof)


@pytest.mark.parametrize("native", [True, False])
def test_final_clock_rechecks_retention_after_late_lease_checks(native):
    conn = Connection()
    prepared_check, pending, receipt = prepared(conn)
    prepared_check.proof["valid_until"] = (conn.now + timedelta(seconds=1)).isoformat()
    prepared_check(conn, "fixture", pending, receipt)
    conn.now += timedelta(seconds=2)
    with pytest.raises(ValueError):
        check_prepared_recovery_clock(
            conn,
            prepared_check if native else None,
            proof=prepared_check.proof,
            pending=pending,
        )


def test_already_stale_proof_defers_before_locks_or_external_io():
    conn = Connection()
    external = []
    proof, pending, receipt = prepared(conn, lambda: external.append(True))
    conn.now += timedelta(seconds=6)
    conn.calls.clear()
    with pytest.raises(CoverageRecoveryDeferred):
        proof(conn, "fixture", pending, receipt)
    assert external == []
    assert not any("FOR " in sql or "advisory" in sql for sql, _ in conn.calls)


def test_database_clock_shift_cannot_extend_outer_monotonic_deadline(monkeypatch):
    import agent_storage.postgres.coverage_recovery_preparation as preparation

    monkeypatch.setattr(preparation, "monotonic", lambda: 100.0)
    conn = Connection()
    proof, pending, receipt = prepared(conn)
    conn.now += timedelta(seconds=2)
    wrapped = prepared_recovery_connection(conn, proof)
    observed = []
    proof = replace(proof, final_authority=lambda deadline: observed.append(deadline))
    conn.now -= timedelta(seconds=1)
    proof(wrapped, "fixture", pending, receipt)
    assert observed == [wrapped.deadline] == [103.0]


def test_native_database_and_schema_are_bound():
    conn = Connection()
    conn.info = SimpleNamespace(host="db-a", port=5432, dbname="zebra")
    proof, pending, receipt = prepared(conn)
    proof.snapshot.bind_database()
    conn.info.host = "db-b"
    with pytest.raises(ValueError, match="database/schema boundary"):
        proof(conn, "fixture", pending, receipt)


def test_unordered_rows_preserve_exact_multiset():
    class Rows(Connection):
        def execute(self, sql, params=None):
            return SimpleNamespace(fetchall=lambda: self.rows)

    conn = Rows()
    conn.rows = [{"id": 1}, {"id": 2}, {"id": 2}]
    snapshot = RecoveryReadSnapshot(conn)
    snapshot.execute("SELECT * FROM evidence").fetchall()
    conn.rows = list(reversed(conn.rows))
    snapshot.revalidate(conn)
    conn.rows.pop()
    with pytest.raises(ValueError, match="evidence changed"):
        snapshot.revalidate(conn)


def test_native_preparation_allows_writer_and_rejects_unversioned_tamper(dsn):  # noqa: F811
    with psycopg.connect(dsn) as conn:
        conn.execute("CREATE TABLE preparation_evidence (id integer PRIMARY KEY, body text)")
        conn.execute("INSERT INTO preparation_evidence VALUES (1,'original')")
    with psycopg.connect(dsn, row_factory=dict_row) as reader:
        reader.execute("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY")
        snapshot = RecoveryReadSnapshot(reader)
        row = snapshot.execute(
            "SELECT * FROM preparation_evidence WHERE id=%s FOR UPDATE", (1,)
        ).fetchone()
        assert row["body"] == "original"
        # This exact UPDATE would block if preparation retained FOR UPDATE.
        with psycopg.connect(dsn) as writer:
            writer.execute("SET LOCAL lock_timeout = '500ms'")
            writer.execute("UPDATE preparation_evidence SET body='tampered' WHERE id=1")
    with psycopg.connect(dsn, row_factory=dict_row) as final:
        with pytest.raises(ValueError, match="evidence changed"):
            snapshot.revalidate(final)


def test_native_finalization_pins_lifecycle_until_commit(dsn):  # noqa: F811
    with psycopg.connect(dsn) as conn:
        conn.execute("CREATE TABLE preparation_lifecycle (id integer PRIMARY KEY, active boolean)")
        conn.execute("INSERT INTO preparation_lifecycle VALUES (1,TRUE)")
    with psycopg.connect(dsn, row_factory=dict_row) as reader:
        reader.execute("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY")
        snapshot = RecoveryReadSnapshot(reader)
        snapshot.execute(
            "SELECT * FROM preparation_lifecycle WHERE id=%s FOR UPDATE", (1,)
        ).fetchone()
    with psycopg.connect(dsn, row_factory=dict_row) as final:
        snapshot.revalidate(final)
        with psycopg.connect(dsn) as writer:
            writer.execute("SET LOCAL lock_timeout = '100ms'")
            with pytest.raises(psycopg.errors.LockNotAvailable):
                writer.execute("UPDATE preparation_lifecycle SET active=FALSE WHERE id=1")


def test_native_cloned_rows_in_another_schema_cannot_finalize(dsn):  # noqa: F811
    with psycopg.connect(dsn, row_factory=dict_row) as reader:
        reader.execute("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY")
        snapshot = RecoveryReadSnapshot(reader)
        snapshot.bind_database()
    with psycopg.connect(dsn, row_factory=dict_row) as final:
        final.execute("SET LOCAL search_path=public")
        with pytest.raises(ValueError, match="database/schema boundary"):
            snapshot.revalidate(final)
