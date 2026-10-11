"""Queue-only scratch fixtures; never connect to application storage."""

import json
import sqlite3
from contextlib import contextmanager
from uuid import UUID, uuid4

import psycopg
from agent_core.domain.identifiers import TaskId
from agent_storage.postgres.database import PostgresDatabase
from agent_storage.postgres.projection_work import PostgresTaskProjectionWorkStore
from agent_storage.postgres.projection_work_migration import TASK_PROJECTION_WORK_MIGRATION
from agent_storage.projection_work import SQLiteTaskProjectionWorkStore
from agent_storage.projection_work_schema import initialize_projection_work
from agent_storage.task_projection_checkpoint_schema import SCHEMA
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb

from tests.agent_storage.test_postgres_scalar_task_replay_headers import install as pg_headers
from tests.agent_storage.test_scalar_task_replay_headers import INSERT, header_database, source_row


class QueueFixture:
    def __init__(self, backend, tmp_path, scratch=None):
        self.backend = backend
        self.task = TaskId(uuid4())
        self.namespace = "local" if backend == "sqlite" else "header-probe"
        self.path = tmp_path / "queue.sqlite"
        self.dsn = None if scratch is None else scratch[0]
        self.role = None if scratch is None else scratch[1]
        if backend == "sqlite":
            with header_database(self.path, self.task) as connection:
                connection.execute("DROP TRIGGER fixture_source_cursor")
                connection.execute("""CREATE TRIGGER fixture_source_cursor
                 AFTER INSERT ON session_events
                 WHEN NEW.task_id IS NOT NULL BEGIN
                 INSERT INTO execution_segments VALUES (NEW.session_id,NEW.task_id,NEW.sequence,1)
                 ON CONFLICT(session_id) DO UPDATE SET event_position_source_cursor=
                   MAX(event_position_source_cursor,excluded.event_position_source_cursor); END""")
                connection.executescript(SCHEMA)
        else:
            with self.connect() as connection:
                pg_headers(connection)
                connection.execute("""CREATE TABLE task_projection_heads (
                 deployment_namespace TEXT NOT NULL,task_id UUID NOT NULL,anchor_key TEXT NOT NULL,
                 projector_version TEXT NOT NULL,through_sequence BIGINT NOT NULL,
                 PRIMARY KEY(deployment_namespace,task_id,anchor_key,projector_version))""")
                connection.execute(
                    "INSERT INTO agent_tasks VALUES (%s,%s,0,'ready')", (self.namespace, self.task)
                )

    @contextmanager
    def connect(self):
        if self.backend == "sqlite":
            connection = sqlite3.connect(self.path, timeout=2)
            connection.row_factory = sqlite3.Row
        else:
            connection = psycopg.connect(self.dsn, row_factory=dict_row)
        try:
            with connection:
                yield connection
        finally:
            connection.close()

    def store(self, version="ag-ui-v1", namespace=None):
        namespace = self.namespace if namespace is None else namespace
        if self.backend == "sqlite":
            return SQLiteTaskProjectionWorkStore(self.path, namespace, version)
        return PostgresTaskProjectionWorkStore(
            PostgresDatabase(self.dsn, deployment_namespace=namespace), version
        )

    def install(self):
        with self.connect() as connection:
            if self.backend == "sqlite":
                initialize_projection_work(connection)
            else:
                for statement in TASK_PROJECTION_WORK_MIGRATION.statements:
                    connection.execute(statement)

    def execute(self, connection, statement, params=()):
        return connection.execute(
            statement if self.backend == "sqlite" else statement.replace("?", "%s"), params
        )

    def append(self, number, *, assigned=True, **kwargs):
        row = source_row(self.task, number, **kwargs)
        with self.connect() as connection:
            if self.backend == "sqlite":
                source = list(row)
                if not assigned:
                    source[6:8] = [None, None]
                connection.execute(INSERT, source)
            else:
                connection.execute(
                    "INSERT INTO session_events "
                    "(deployment_namespace,event_id,session_id,sequence,event_type,"
                    "payload,actor,task_id,task_sequence,event_bytes_bound) "
                    "VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)",
                    (
                        self.namespace,
                        UUID(row[0]),
                        UUID(row[1]),
                        number,
                        row[3],
                        Jsonb(json.loads(row[4])),
                        row[5],
                        self.task if assigned else None,
                        number if assigned else None,
                        row[8],
                    ),
                )
            if assigned:
                self.execute(
                    connection,
                    "UPDATE agent_tasks SET next_event_sequence=? WHERE task_id=?",
                    (number + 1, str(self.task)),
                )
        return row[0]

    def set_head(self, work, through=None):
        through = work.requested_through if through is None else through
        with self.connect() as connection:
            fields = (
                "deployment_namespace,task_id,anchor_key,projector_version,through_sequence"
                if self.backend == "postgres"
                else "deployment_namespace,task_id,anchor_key,projector_version,"
                "through_sequence,last_event_id"
            )
            values = (
                self.namespace,
                str(self.task),
                str(work.scope.anchor_event_id),
                work.scope.projector_version,
                through,
            )
            if self.backend == "sqlite":
                values += (str(UUID(int=through + 1)),)
            self.execute(
                connection,
                f"INSERT INTO task_projection_heads ({fields}) "
                f"VALUES ({','.join('?' for _ in values)}) "
                "ON CONFLICT(deployment_namespace,task_id,anchor_key,projector_version) "
                "DO UPDATE SET through_sequence=excluded.through_sequence",
                values,
            )

    def work_rows(self):
        with self.connect() as connection:
            return [
                dict(row)
                for row in connection.execute(
                    "SELECT * FROM task_projection_work ORDER BY anchor_sequence"
                ).fetchall()
            ]

    def table_counts(self):
        with self.connect() as connection:
            return tuple(
                connection.execute(f"SELECT COUNT(*) AS n FROM {name}").fetchone()["n"]
                for name in (
                    "task_projection_work_projectors",
                    "task_projection_work_routes",
                    "task_projection_work",
                    "task_projection_heads",
                )
            )
