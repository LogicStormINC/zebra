"""One native prefix scan preserves inclusive cutoffs and scope isolation."""
# ruff: noqa: F811

from uuid import uuid4

import psycopg
from agent_storage.postgres.command_wakeup_recovery_proof import _accepted_prefix_counts
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb

from tests.agent_storage.test_postgres_command_wakeup import dsn, postgres_dsn  # noqa: F401


def test_no_prefix_requires_no_database_read():
    assert _accepted_prefix_counts(None, "deployment", {}, {}, {}) == {}


def test_native_prefix_cutoffs_are_inclusive_scoped_and_fresh(dsn):
    session = uuid4()
    scope = {"namespace": "coverage", "run_id": "run"}
    pending = {"session_id": session}
    cutoffs = {0: 0, 9: 0, 10: 2, 11: 2, 19: 2, 20: 5, 30: 5, 49: 5, 50: 6, 60: 6}
    with psycopg.connect(dsn, row_factory=dict_row) as connection:
        connection.execute(
            "CREATE TEMP TABLE session_events (deployment_namespace text, session_id uuid,"
            "sequence bigint,event_type text,payload jsonb) ON COMMIT DROP"
        )
        rows = [
            ("deployment", session, sequence, "coverage_batch_accepted",
             Jsonb(scope | {"result_count": count}))
            for sequence, count in ((10, 2), (20, 3), (30, None), (40, 0), (50, 1))
        ]
        rows += [
            (deployment, owner, 15, event_type, Jsonb(content | {"result_count": 999}))
            for deployment, owner, event_type, content in (
                ("other", session, "coverage_batch_accepted", scope),
                ("deployment", uuid4(), "coverage_batch_accepted", scope),
                ("deployment", session, "coverage_batch_accepted", scope | {"run_id": "other"}),
                ("deployment", session, "coverage_batch_accepted", scope | {"namespace": "other"}),
                ("deployment", session, "other_event", scope),
            )
        ]
        connection.cursor().executemany("INSERT INTO session_events VALUES (%s,%s,%s,%s,%s)", rows)
        assert _accepted_prefix_counts(connection, "deployment", pending, scope, cutoffs) == cutoffs
        connection.execute(
            "UPDATE session_events SET payload=jsonb_set(payload,'{result_count}','4') "
            "WHERE sequence=20"
        )
        expected = {mark: count + (mark >= 20) for mark, count in cutoffs.items()}
        actual = _accepted_prefix_counts(connection, "deployment", pending, scope, cutoffs)
        assert actual == expected
