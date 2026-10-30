"""Run with ZEBRA_TEST_POSTGRES_DSN: real header SQL, temporary tables only."""

import os
from unittest import SkipTest
from uuid import UUID

import psycopg
from agent_core.domain.identifiers import TaskId
from agent_core.domain.sessions import SessionStatus
from agent_storage.postgres.agent_tasks import read_task_header
from psycopg.rows import dict_row


def test_header_safety_join_is_scoped_and_preserves_shadow() -> None:
    dsn = os.environ.get("ZEBRA_TEST_POSTGRES_DSN")
    if not dsn:
        raise SkipTest("set ZEBRA_TEST_POSTGRES_DSN for actual PostgreSQL")
    task = TaskId(UUID("f8db15f3-daf5-4406-8b83-ab5e853f15a5"))
    with psycopg.connect(dsn, row_factory=dict_row) as connection:
        try:
            connection.execute(
                "CREATE TEMP TABLE agent_tasks (deployment_namespace text, task_id uuid, "
                "active_segment_id uuid, next_event_sequence bigint, event_position_state text)"
            )
            connection.execute(
                "CREATE TEMP TABLE session_observation_headers (deployment_namespace text, "
                "session_id text, title text, status text, current_sequence bigint, "
                "title_truncated boolean, clarification_id text, clarification_invalid boolean)"
            )
            connection.execute(
                "CREATE TEMP TABLE agent_safety_overrides (deployment_namespace text, session_id "
                "uuid, kind text, shadow boolean, PRIMARY KEY(deployment_namespace,session_id))"
            )
            connection.execute(
                "INSERT INTO pg_temp.agent_tasks VALUES ('own',%s,%s,4,'ready')", (task, task)
            )
            connection.execute(
                "INSERT INTO pg_temp.session_observation_headers VALUES "
                "('own',%s,'task','ready',3,false,NULL,false)",
                (str(task),),
            )
            assert read_task_header(connection, "other", task) is None
            header = read_task_header(connection, "own", task)
            assert header is not None and header.status is SessionStatus.READY
            connection.execute(
                "INSERT INTO pg_temp.agent_safety_overrides VALUES "
                "('other',%s,'dead_letter',false)",
                (task,),
            )
            assert read_task_header(connection, "own", task).status is SessionStatus.READY
            for kind, shadow, expected in [
                ("failure_count", False, SessionStatus.READY),
                ("dead_letter", True, SessionStatus.READY),
                ("dead_letter", False, SessionStatus.FAILED),
                ("watchdog", False, SessionStatus.FAILED),
                ("zombie_repair", False, SessionStatus.FAILED),
            ]:
                connection.execute(
                    "INSERT INTO pg_temp.agent_safety_overrides VALUES ('own',%s,%s,%s) ON "
                    "CONFLICT(deployment_namespace,session_id) DO UPDATE SET "
                    "kind=excluded.kind,shadow=excluded.shadow",
                    (task, kind, shadow),
                )
                result = read_task_header(connection, "own", task)
                assert result is not None and result.status is expected
                assert result.active_segment_sequence == 3
            connection.execute("DELETE FROM pg_temp.session_observation_headers")
            assert read_task_header(connection, "own", task).status is SessionStatus.FAILED
        finally:
            connection.rollback()


if __name__ == "__main__":
    test_header_safety_join_is_scoped_and_preserves_shadow()
    print("actual PostgreSQL header, shadow, terminal, tenant and stale projection checks passed")
