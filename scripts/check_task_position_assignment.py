"""Run with ZEBRA_TEST_POSTGRES_DSN; uses and drops only its own schema."""

import os
from datetime import UTC, datetime
from unittest.mock import patch
from uuid import uuid4

import psycopg
from agent_core.application.session_bootstrap import (
    SessionBootstrapCommand,
    SessionBootstrapService,
)
from agent_core.application.workspace_projection import rebuild_workspace
from agent_core.ports.idempotency_store import IdempotencyRecord
from agent_core.ports.task_admission_transaction import TaskAdmissionRequest
from agent_storage.postgres import apply_postgres_migrations
from agent_storage.postgres.task_admission import PostgresTaskAdmissionTransaction
from agent_storage.postgres.task_event_positions import _assign
from agent_storage.postgres.task_lineage import PostgresAgentTaskConflictError
from psycopg import sql
from psycopg.conninfo import make_conninfo
from psycopg.rows import dict_row


def check() -> None:
    configured = os.environ["ZEBRA_TEST_POSTGRES_DSN"]
    schema = "assignment_check_" + uuid4().hex
    with psycopg.connect(configured) as connection:
        connection.execute(sql.SQL("CREATE SCHEMA {}").format(sql.Identifier(schema)))
    try:
        dsn = make_conninfo(configured, options=f"-c search_path={schema}")
        apply_postgres_migrations(dsn)
        bootstrap = SessionBootstrapService().build(
            SessionBootstrapCommand(title="assignment", user_input="check", workspace_root="/tmp")
        )
        request = TaskAdmissionRequest(
            events=tuple(bootstrap.events),
            session=bootstrap.session,
            workspace=rebuild_workspace(list(bootstrap.events)),
            idempotency=IdempotencyRecord(
                action="assignment.check",
                idempotency_key=uuid4().hex,
                request_hash="a" * 64,
                status_code=201,
                response_body={},
                created_at=datetime.now(UTC),
            ),
        )
        transaction = PostgresTaskAdmissionTransaction(dsn, deployment_namespace="assignment-check")
        queries: list[str] = []
        original = psycopg.Cursor.execute

        def measured(self, query, *args, **kwargs):
            queries.append(" ".join(str(query).split()))
            return original(self, query, *args, **kwargs)

        with patch.object(psycopg.Cursor, "execute", measured):
            receipt = transaction.admit(request)
        # New mappings take the native INSERT path; no speculative pre-read per Event.
        assert not any(
            q.startswith("SELECT task_id,task_sequence,segment_id,segment_sequence")
            for q in queries
        ), "new mapping still pre-read"
        assert len(
            [
                q
                for q in queries
                if q.startswith("UPDATE session_events SET task_id=") and "event_bytes_bound=" in q
            ]
        ) == len(request.events)
        ns, task_id = "assignment-check", receipt.task_id
        with psycopg.connect(dsn, row_factory=dict_row) as connection:
            rows = connection.execute(
                "SELECT event_id,session_id,sequence,task_id AS source_task,"
                "task_sequence AS source_position,event_bytes_bound,xmin::text FROM session_events "
                "WHERE deployment_namespace=%s AND task_id=%s ORDER BY sequence",
                (ns, task_id),
            ).fetchall()
            assert [r["source_position"] for r in rows] == list(range(len(request.events)))
            assert all(r["event_bytes_bound"] > 0 for r in rows)
            # Correct existing mappings remain unchanged, including native source witnesses.
            assert _assign(connection, ns, task_id, rows[0], 0) == 0
            assert (
                connection.execute(
                    "SELECT xmin::text FROM session_events WHERE event_id=%s",
                    (rows[0]["event_id"],),
                ).fetchone()["xmin"]
                == rows[0]["xmin"]
            )
            # Missing mapping is rebuilt; a conflicting mapping must fail closed.
            connection.execute(
                "DELETE FROM task_event_index WHERE event_id=%s", (rows[0]["event_id"],)
            )
            assert _assign(connection, ns, task_id, rows[0], 0) == 1
            connection.execute(
                "UPDATE task_event_index SET task_sequence=99 WHERE event_id=%s",
                (rows[0]["event_id"],),
            )
            try:
                _assign(connection, ns, task_id, rows[0], 0)
            except PostgresAgentTaskConflictError:
                pass
            else:
                raise AssertionError("conflicting mapping accepted")
            connection.rollback()
        assert transaction.admit(request).idempotent_replay
        fresh = SessionBootstrapService().build(
            SessionBootstrapCommand(title="rollback", user_input="check", workspace_root="/tmp")
        )
        with psycopg.connect(dsn, row_factory=dict_row) as connection:
            transaction.admit_in_transaction(
                connection,
                ns,
                TaskAdmissionRequest(
                    events=tuple(fresh.events),
                    session=fresh.session,
                    workspace=rebuild_workspace(list(fresh.events)),
                ),
            )
            connection.rollback()
            assert (
                connection.execute(
                    "SELECT 1 FROM session_events WHERE session_id=%s", (fresh.session.session_id,)
                ).fetchone()
                is None
            )
        print(
            "native assignment/replay/rollback/conflict and source witness checks passed"
        )
    finally:
        with psycopg.connect(configured) as connection:
            connection.execute(sql.SQL("DROP SCHEMA {} CASCADE").format(sql.Identifier(schema)))


if __name__ == "__main__":
    check()
