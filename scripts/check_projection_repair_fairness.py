"""Native regression: derived repair must release its row before a writer times out.

Run with ZEBRA_TEST_POSTGRES_DSN pointing at a disposable local PostgreSQL server
with CREATEDB. Creates and drops one unique database; never invokes a model.
"""

import json
import os
import threading
from pathlib import Path
from time import monotonic
from uuid import uuid4

import psycopg
from agent_core.application import SessionBootstrapCommand, SessionBootstrapService
from agent_core.contracts.session_commands import SessionCommand, SessionCommandKind
from agent_core.domain.events import EventActor, EventType, SessionEvent
from agent_storage import (
    PostgresAgentTaskStore,
    PostgresEventStore,
    PostgresProjectionStore,
    apply_postgres_migrations,
)
from agent_storage.postgres.database import PostgresDatabase
from agent_storage.postgres.projection_work import PostgresTaskProjectionWorkStore, _WorkConnection
from psycopg import sql
from psycopg.conninfo import conninfo_to_dict, make_conninfo


def check(dsn: str) -> None:
    namespace = "repair-fairness"
    boot = SessionBootstrapService().build(
        SessionBootstrapCommand(title="Fairness", user_input="check", workspace_root=Path("/tmp"))
    )
    events = PostgresEventStore(dsn, deployment_namespace=namespace)
    for event in boot.events:
        events.append(event)
    PostgresProjectionStore(dsn, deployment_namespace=namespace).save_session(boot.session)
    tasks = PostgresAgentTaskStore(dsn, deployment_namespace=namespace)
    task = tasks.ensure_for_session(boot.session.session_id).task_id
    while not tasks.backfill_event_positions(task):
        pass
    while not tasks.backfill_replay_headers(task):
        pass
    sequence = boot.session.current_sequence + 1
    command = SessionCommand(
        session_id=boot.session.session_id, kind=SessionCommandKind.RUN,
        expected_revision=sequence - 1, idempotency_key="fairness", payload={"run_id": "fairness"},
    )
    events.append(SessionEvent.create(
        session_id=boot.session.session_id, sequence=sequence,
        event_type=EventType.SESSION_COMMAND_ACCEPTED, actor=EventActor.USER,
        payload=command.event_payload(),
    ))
    database = PostgresDatabase(dsn, deployment_namespace=namespace)
    work = PostgresTaskProjectionWorkStore(database, "ag-ui-v1")
    work.enable_projection_work()
    work.bootstrap_projection_work()
    while work.repair_projection_work(task).needs_repair:
        pass

    def title(position: int) -> SessionEvent:
        return SessionEvent.create(
            session_id=boot.session.session_id, sequence=position,
            event_type=EventType.SESSION_TITLE_UPDATED, actor=EventActor.SYSTEM,
            payload={"title": "fairness"},
        )

    for position in range(sequence + 1, sequence + 31):
        events.append(title(position))
    with database.connect() as connection:
        connection.execute(
            "UPDATE task_projection_work_routes SET observed_through=%s,needs_repair=1 "
            "WHERE deployment_namespace=%s AND task_id=%s", (sequence, namespace, str(task)),
        )
        connection.execute(
            "UPDATE task_projection_work SET requested_through=%s "
            "WHERE deployment_namespace=%s AND task_id=%s", (sequence, namespace, str(task)),
        )
    entered, failures, repairs = threading.Event(), [], []
    original = _WorkConnection.execute

    def slow_header(self, statement, params=None):
        if statement.startswith("DO "):
            params = (params[0].replace("BEGIN ", "BEGIN PERFORM pg_sleep(0.02); ", 1),)
        result = original(self, statement, params)
        if statement.startswith("DO "):
            entered.set()  # The real repair now owns the queue row lock.
        return result

    def repair() -> None:
        try:
            repairs.append(work.repair_projection_work(task))
        except Exception as exc:
            failures.append(type(exc).__name__)

    _WorkConnection.execute = slow_header
    thread = threading.Thread(target=repair)
    writer_error = None
    candidate = title(sequence + 31)
    try:
        thread.start()
        assert entered.wait(5), "repair did not acquire its native row lock"
        options = conninfo_to_dict(dsn).get("options", "") + " -c lock_timeout=200ms"
        writer = PostgresEventStore(
            make_conninfo(dsn, options=options), deployment_namespace=namespace
        )
        started = monotonic()
        try:
            writer.append(candidate)
        except psycopg.errors.LockNotAvailable:
            writer_error = "LockNotAvailable"
        writer_ms = (monotonic() - started) * 1000
    finally:
        thread.join(5)
        _WorkConnection.execute = original
    assert not thread.is_alive() and not failures, failures
    print(json.dumps({"writer_error": writer_error, "writer_ms": round(writer_ms, 2)}))
    assert writer_error is None, "derived repair starved a canonical event COMMIT"
    assert len(repairs) == 1 and repairs[0].needs_repair
    assert sequence < repairs[0].after_sequence < sequence + 30  # Committed partial prefix.
    for _ in range(100):
        if not work.repair_projection_work(task).needs_repair:
            break
    else:
        raise AssertionError("resumable repair did not converge")
    source = events.list_for_session(boot.session.session_id)
    assert [event.sequence for event in source] == list(range(sequence + 32))
    assert sum(event.event_id == candidate.event_id for event in source) == 1
    (pending,) = work.read_pending_projection_work()
    print(json.dumps({"requested": pending.requested_through, "expected": sequence + 31}))
    assert pending.requested_through == sequence + 31


if __name__ == "__main__":
    configured = os.environ["ZEBRA_TEST_POSTGRES_DSN"]
    assert conninfo_to_dict(configured)["host"] in ("localhost", "127.0.0.1")
    name = "projection_fairness_" + uuid4().hex
    admin = make_conninfo(configured, dbname="postgres")
    with psycopg.connect(admin, autocommit=True) as connection:
        connection.execute(sql.SQL("CREATE DATABASE {}").format(sql.Identifier(name)))
    try:
        isolated = make_conninfo(configured, dbname=name)
        apply_postgres_migrations(isolated)
        check(isolated)
    finally:
        with psycopg.connect(admin, autocommit=True) as connection:
            connection.execute(
                sql.SQL("DROP DATABASE {} WITH (FORCE)").format(sql.Identifier(name))
            )
