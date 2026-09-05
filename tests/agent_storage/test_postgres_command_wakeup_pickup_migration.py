"""v43 -> v44 preserves existing pending identity and derives every canonical lane."""

from uuid import uuid4

import psycopg
import pytest
from agent_storage.postgres import migration_runner
from agent_storage.postgres.command_wakeup import command_scope_key
from psycopg import sql
from psycopg.conninfo import make_conninfo

from tests.agent_storage.test_postgres_command_wakeup import NAMESPACE, _seed
from tests.agent_storage.test_postgres_command_wakeup import postgres_dsn as _pg_fixture
from tests.agent_storage.test_postgres_command_wakeup_control import _intent
from tests.agent_storage.test_postgres_command_wakeup_discovery import SCOPE
from tests.agent_storage.test_postgres_command_wakeup_message import _message
from tests.agent_storage.test_postgres_command_wakeup_recovery import _rows

postgres_dsn = _pg_fixture


@pytest.fixture
def legacy_dsn(postgres_dsn, monkeypatch):
    schema = f"command_pickup_migration_{uuid4().hex}"
    with psycopg.connect(postgres_dsn) as connection:
        connection.execute(sql.SQL("CREATE SCHEMA {}").format(sql.Identifier(schema)))
    dsn = make_conninfo(postgres_dsn, options=f"-c search_path={schema}")
    try:
        with monkeypatch.context() as target:
            target.setattr(
                migration_runner,
                "MIGRATIONS",
                tuple(
                    migration
                    for migration in migration_runner.MIGRATIONS
                    if migration.version <= 44
                ),
            )
            with monkeypatch.context() as legacy:
                legacy.setattr(
                    migration_runner,
                    "MIGRATIONS",
                    tuple(
                        migration
                        for migration in migration_runner.MIGRATIONS
                        if migration.version <= 43
                    ),
                )
                migration_runner.apply_postgres_migrations(dsn)
            yield dsn
    finally:
        with psycopg.connect(postgres_dsn) as connection:
            connection.execute(sql.SQL("DROP SCHEMA {} CASCADE").format(sql.Identifier(schema)))


def test_v44_backfills_exact_canonical_kinds_without_rewriting_existing_rows(legacy_dsn):
    session = _seed(legacy_dsn)
    expected = {}
    for kind in ("run", "resume", "message", "cancel", "stop", "suspend"):
        event = (
            _message(legacy_dsn, session.session_id)
            if kind == "message"
            else _intent(legacy_dsn, session.session_id, kind)
        )
        expected[event.event_id] = kind
        with psycopg.connect(legacy_dsn) as connection:
            connection.execute(
                """INSERT INTO session_command_pending (deployment_namespace, scope_key, command_id,
                   session_id, accepted_event_id, accepted_sequence, tenant_id, workspace_id)
                   VALUES (%s,%s,%s,%s,%s,%s,%s,%s)""",
                (
                    NAMESPACE,
                    command_scope_key(SCOPE),
                    event.payload["command_id"],
                    session.session_id,
                    event.event_id,
                    event.sequence,
                    SCOPE.tenant_id,
                    SCOPE.workspace_id,
                ),
            )
    before = _rows(legacy_dsn, "session_command_pending")
    canonical = _rows(legacy_dsn, "session_events")
    checksums = _rows(legacy_dsn, "zebra_schema_migrations")
    migration_runner.apply_postgres_migrations(legacy_dsn)
    after = _rows(legacy_dsn, "session_command_pending")
    assert {row["accepted_event_id"]: row["command_kind"] for row in after} == expected
    assert [
        {key: value for key, value in row.items() if key != "command_kind"} for row in after
    ] == before
    assert _rows(legacy_dsn, "session_events") == canonical
    assert [
        row for row in _rows(legacy_dsn, "zebra_schema_migrations") if row["version"] <= 43
    ] == checksums
    migration_runner.apply_postgres_migrations(legacy_dsn)
    assert _rows(legacy_dsn, "session_command_pending") == after
