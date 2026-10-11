"""Actual recovery SQL: native bounds, scoped rows and no oversized payload transfer."""
# ruff: noqa: F811

from types import SimpleNamespace

import psycopg
import pytest
from agent_storage.postgres.coverage_recovery_preparation import RecoveryReadSnapshot
from psycopg.rows import dict_row

from tests.agent_storage.test_postgres_command_wakeup import postgres_dsn  # noqa: F401
from tests.worker.test_coverage_recovery_transcript import recovery_phase


def queries(monkeypatch):
    captured = {}

    def capture(sql, params):
        if "octet_length(to_jsonb(e)" in sql:
            captured["history"] = (sql, params)
        elif "octet_length(to_jsonb(u)" in sql:
            captured["units"] = (sql, params)

    run, _, _ = recovery_phase(monkeypatch, state=None, native_read=capture)
    run()
    assert set(captured) == {"history", "units"}
    return captured


@pytest.mark.parametrize("kind", ["history", "units"])
@pytest.mark.parametrize("case", ["empty", "exact_bytes", "excess_bytes", "excess_count"])
def test_native_recovery_bounds_and_payload_transfer(postgres_dsn, monkeypatch, kind, case):
    statement, params = queries(monkeypatch)[kind]
    params = list(params)
    with psycopg.connect(postgres_dsn, row_factory=dict_row) as connection:
        if kind == "history":
            table, identity, aggregate = "session_events", "event_id", "history"
            connection.execute("""CREATE TEMP TABLE session_events (
                deployment_namespace text,session_id text,event_id text,
                sequence int,event_type text,payload jsonb) ON COMMIT PRESERVE ROWS""")
            count = 0 if case == "empty" else 4097 if case == "excess_count" else 2
            connection.execute("""INSERT INTO session_events
                SELECT %s,%s,i::text,i,'synthetic','{}'::jsonb
                FROM generate_series(1,%s) i""", (*params[:2], count))
            # Large foreign histories cannot affect this Session's bounds or rows.
            connection.execute("""INSERT INTO session_events VALUES
                ('other',%s,'foreign',1,'synthetic',jsonb_build_object('x',repeat('x',10000)))""",
                (params[1],))
            connection.execute("""INSERT INTO session_events VALUES
                (%s,'other','foreign-session',1,'synthetic','{}'::jsonb)""", (params[0],))
            where, scope = "deployment_namespace=%s AND session_id=%s", params[:2]
            byte_index = 4
        else:
            table, identity, aggregate = "coverage_units", "unit_digest", "unit"
            connection.execute("""CREATE TEMP TABLE coverage_units (
                deployment_namespace text,namespace text,run_id text,
                unit_digest text,unit_key jsonb,result jsonb,ordinal int)
                ON COMMIT PRESERVE ROWS""")
            count = 0 if case == "empty" else 3 if case == "excess_count" else 2
            params[6], params[8] = (0 if case == "empty" else 2), 3
            connection.execute("""INSERT INTO coverage_units
                SELECT %s,%s,%s,i::text,'{}'::jsonb,'{}'::jsonb,i
                FROM generate_series(1,%s) i""", (*params[:3], count))
            connection.execute("""INSERT INTO coverage_units VALUES
                (%s,'other',%s,'foreign','{}'::jsonb,jsonb_build_object('x',repeat('x',10000)),1)""",
                (params[0], params[2]))
            connection.execute("""INSERT INTO coverage_units VALUES
                ('other',%s,%s,'foreign-deployment','{}'::jsonb,'{}'::jsonb,1),
                (%s,%s,'other','foreign-run','{}'::jsonb,'{}'::jsonb,1)""",
                (params[1], params[2], params[0], params[1]))
            where, scope = "deployment_namespace=%s AND namespace=%s AND run_id=%s", params[:3]
            byte_index = 7
        size = connection.execute(
            f"SELECT coalesce(sum(octet_length(to_jsonb(t)::text)),0) AS bytes "
            f"FROM {table} t WHERE {where}", scope,
        ).fetchone()["bytes"]
        if case in {"exact_bytes", "excess_bytes"}:
            params[byte_index] = size - (case == "excess_bytes")
        connection.commit()
        connection.execute("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY")
        snapshot = RecoveryReadSnapshot(connection, reuse_reads=True)
        snapshot.bind_database()
        rows = snapshot.execute(statement, params).fetchall()
        assert snapshot.execute(statement, params).fetchall() == rows
        assert len(snapshot.reads) == 1
        assert rows and rows[0][f"{aggregate}_count"] == count
        assert rows[0][f"{aggregate}_bytes"] == size
        if case == "exact_bytes":
            assert [row[identity] for row in rows] == ["1", "2"]
        else:
            assert len(rows) == 1 and rows[0][identity] is None
        connection.rollback()
        snapshot.revalidate(connection)
        if case == "exact_bytes":
            change = "event_type='alteredxx'" if kind == "history" else "result='[]'::jsonb"
            connection.execute(f"UPDATE {table} SET {change} WHERE {where}", scope)
            # Same count and byte length must not hide changed native source rows.
            changed = connection.execute(statement, params).fetchall()
            assert changed[0][f"{aggregate}_count"] == rows[0][f"{aggregate}_count"]
            assert changed[0][f"{aggregate}_bytes"] == rows[0][f"{aggregate}_bytes"]
            assert changed != rows
            with pytest.raises(ValueError, match="evidence changed"):
                snapshot.revalidate(connection)
            connection.rollback()
        connection.execute(f"DELETE FROM {table} WHERE {where}", scope)
        if count:
            with pytest.raises(ValueError, match="evidence changed"):
                snapshot.revalidate(connection)


@pytest.mark.parametrize("kind", ["history", "units"])
def test_recovery_rejects_bounds_before_replay(monkeypatch, kind):
    def bounded(sql, params):
        if "octet_length(to_jsonb(e)" in sql and kind == "history":
            rows = [{"history_count": 4097, "history_bytes": 1, "event_id": None}]
        elif "octet_length(to_jsonb(u)" in sql and kind == "units":
            rows = [{"unit_count": 1, "unit_bytes": 1, "unit_digest": None}]
        else:
            return None
        return SimpleNamespace(fetchall=lambda: rows)

    run, counts, _ = recovery_phase(monkeypatch, state=None, native_read=bounded)
    with pytest.raises(ValueError, match="bounded Session history|projections exceed frozen"):
        run()
    assert counts["ledger"] == 0
