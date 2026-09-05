"""v48 preserves existing exact command obligations while adding a direct anchor."""

from uuid import uuid4

import psycopg
import pytest
from agent_storage.postgres import migration_runner
from psycopg import sql
from psycopg.conninfo import make_conninfo

from tests.agent_storage.test_postgres_command_runtime_cleanup import _prepare_cleanup
from tests.agent_storage.test_postgres_command_wakeup import postgres_dsn as _pg_fixture
from tests.agent_storage.test_postgres_direct_control import _rows

postgres_dsn = _pg_fixture


@pytest.fixture
def legacy_dsn(postgres_dsn, monkeypatch):
    schema = f"direct_migration_{uuid4().hex}"
    with psycopg.connect(postgres_dsn) as connection:
        connection.execute(sql.SQL("CREATE SCHEMA {}").format(sql.Identifier(schema)))
    dsn = make_conninfo(postgres_dsn, options=f"-c search_path={schema}")
    try:
        with monkeypatch.context() as legacy:
            legacy.setattr(
                migration_runner,
                "MIGRATIONS",
                tuple(m for m in migration_runner.MIGRATIONS if m.version <= 47),
            )
            migration_runner.apply_postgres_migrations(dsn)
        yield dsn
    finally:
        with psycopg.connect(postgres_dsn) as connection:
            connection.execute(sql.SQL("DROP SCHEMA {} CASCADE").format(sql.Identifier(schema)))


def test_existing_cleanup_fence_status_and_command_identity_survive_v48(legacy_dsn):
    _prepare_cleanup(legacy_dsn)
    with psycopg.connect(legacy_dsn) as connection:
        connection.execute("""UPDATE command_runtime_cleanup SET status='cleaning',
            claim_owner='test',claim_fence=7,lease_expires_at=clock_timestamp()+interval '1 minute',
            attempts=3""")
    before = _rows(legacy_dsn, "command_runtime_cleanup")
    canonical = _rows(legacy_dsn, "session_events")
    migration_runner.apply_postgres_migrations(legacy_dsn)
    after = _rows(legacy_dsn, "command_runtime_cleanup")
    assert after[0]["cleanup_id"] == before[0]["accepted_event_id"]
    assert after[0]["direct_operation_id"] is None
    assert [
        {k: v for k, v in row.items() if k not in ("cleanup_id", "direct_operation_id")}
        for row in after
    ] == before
    assert _rows(legacy_dsn, "session_events") == canonical
    migration_runner.apply_postgres_migrations(legacy_dsn)
    assert _rows(legacy_dsn, "command_runtime_cleanup") == after
