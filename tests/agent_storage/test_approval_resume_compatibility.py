"""Real PG forward migration: old source/header bytes survive, future trusted wakes retain Run."""

import psycopg
from agent_core.domain.events import EventActor
from agent_storage import PostgresAgentTaskStore, PostgresEventStore, bootstrap_control_plane_epoch
from agent_storage.postgres import migration_runner
from agent_storage.postgres.migrations import MIGRATIONS

from tests.agent_storage.test_postgres_agent_tasks import _seed_session
from tests.agent_storage.test_postgres_migrations import isolated_migration_dsn as _isolated
from tests.agent_storage.test_task_replay_headers import _command

isolated_migration_dsn = _isolated


def test_pg113_keeps_issued_migrations_and_history(isolated_migration_dsn, tmp_path, monkeypatch):
    dsn = isolated_migration_dsn
    with monkeypatch.context() as old:
        old.setattr(migration_runner, "MIGRATIONS", MIGRATIONS[:-1])
        migration_runner.apply_postgres_migrations(dsn)
        bootstrap_control_plane_epoch(dsn, deployment_namespace="compat")
        sid = _seed_session(dsn, "compat", tmp_path / "old", "Old")
        tasks = PostgresAgentTaskStore(dsn, deployment_namespace="compat")
        events = PostgresEventStore(dsn, deployment_namespace="compat")
        task = tasks.ensure_for_session(sid)
        original = _command(events, task)
        with psycopg.connect(dsn) as db:
            before = db.execute(
                "SELECT row_to_json(e)::text FROM session_events e ORDER BY sequence"
            ).fetchall()
            checksums = db.execute(
                "SELECT version,name,checksum FROM zebra_schema_migrations ORDER BY version"
            ).fetchall()
    migration_runner.apply_postgres_migrations(dsn)
    with psycopg.connect(dsn) as db:
        assert (
            db.execute(
                "SELECT row_to_json(e)::text FROM session_events e ORDER BY sequence"
            ).fetchall()
            == before
        )
        assert (
            db.execute(
                "SELECT version,name,checksum FROM zebra_schema_migrations "
                "WHERE version<113 ORDER BY version"
            ).fetchall()
            == checksums
        )
    resumed = _command(
        events, task, kind="resume", run=None, actor=EventActor.HARNESS, key="approval-resume:"
    )
    assert tasks.read_event_header(task.task_id, resumed.sequence).internal_continuation
    assert tasks.read_latest_run_header(task.task_id).anchor.event_id == original.event_id
    forged = _command(
        events, task, kind="resume", run=None, actor=EventActor.USER, key="approval-resume:"
    )
    assert not tasks.read_event_header(task.task_id, forged.sequence).internal_continuation
