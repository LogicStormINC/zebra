"""Native no-write check: ZEBRA_TEST_POSTGRES_DSN=... uv run python this_file.py.

Requires an already migrated disposable PostgreSQL database. No model or fixture.
"""

import os
from contextvars import ContextVar
from functools import wraps
from unittest.mock import patch
from uuid import uuid4

import psycopg
from agent_core.ports.task_projection_checkpoints import CheckpointNotReady
from agent_storage import PostgresAgentTaskStore
from agent_storage.postgres.task_lineage import PostgresAgentTaskConflictError


def check(dsn: str) -> None:
    store = PostgresAgentTaskStore(dsn, deployment_namespace="snapshot-check-" + uuid4().hex)
    depth = ContextVar("query_depth", default=0)
    statements: list[str] = []

    def counted(method):
        @wraps(method)
        def execute(cursor, statement, *args, **kwargs):
            token = depth.set(depth.get() + 1)
            try:
                return method(cursor, statement, *args, **kwargs)
            finally:
                if depth.get() == 1:
                    statements.append(statement)
                depth.reset(token)
        return execute

    with (
        patch.object(psycopg.Cursor, "execute", counted(psycopg.Cursor.execute)),
        patch.object(psycopg.ClientCursor, "execute", counted(psycopg.ClientCursor.execute)),
    ):
        for read, error in (
            (lambda: store.read_latest_run_header(uuid4()), CheckpointNotReady),
            (lambda: store.read_run_header(uuid4(), "missing"), PostgresAgentTaskConflictError),
        ):
            statements.clear()
            try:
                read()
            except error:
                pass
            else:
                raise AssertionError("missing canonical source was accepted")
            assert len(statements) == 1, (
                f"single snapshot needs one statement, got {len(statements)}"
            )
            assert statements[0].lstrip().startswith(("SELECT", "WITH")), statements
    print("latest/explicit Run: one native statement each, missing source rejected, no writes")


if __name__ == "__main__":
    check(os.environ["ZEBRA_TEST_POSTGRES_DSN"])
