"""v48 -> v49 capacity defaults and stable fair-order backfill."""

from uuid import uuid4

import psycopg
import pytest
from agent_storage.postgres import migration_runner
from agent_storage.postgres.command_wakeup import (
    command_scope_key,
    record_command_wakeup_in_transaction,
)
from psycopg import sql
from psycopg.conninfo import make_conninfo
from psycopg.rows import dict_row

from tests.agent_storage.test_postgres_command_wakeup import NAMESPACE, _seed
from tests.agent_storage.test_postgres_command_wakeup import postgres_dsn as _pg_fixture
from tests.agent_storage.test_postgres_command_wakeup_control import _intent
from tests.agent_storage.test_postgres_command_wakeup_discovery import SCOPE
from tests.agent_storage.test_postgres_command_wakeup_recovery import _rows

postgres_dsn = _pg_fixture


@pytest.fixture
def legacy_dsn(postgres_dsn, monkeypatch):
    schema = f"command_capacity_migration_{uuid4().hex}"
    with psycopg.connect(postgres_dsn) as connection:
        connection.execute(sql.SQL("CREATE SCHEMA {}").format(sql.Identifier(schema)))
    dsn = make_conninfo(postgres_dsn, options=f"-c search_path={schema}")
    try:
        with monkeypatch.context() as legacy:
            legacy.setattr(
                migration_runner,
                "MIGRATIONS",
                tuple(item for item in migration_runner.MIGRATIONS if item.version <= 48),
            )
            migration_runner.apply_postgres_migrations(dsn)
        yield dsn
    finally:
        with psycopg.connect(postgres_dsn) as connection:
            connection.execute(sql.SQL("DROP SCHEMA {} CASCADE").format(sql.Identifier(schema)))


def test_v49_backfills_stable_scope_sequence_and_capacity_defaults(legacy_dsn):
    session = _seed(legacy_dsn)
    with psycopg.connect(legacy_dsn) as connection:
        connection.execute(
            "INSERT INTO command_wakeup_rollouts (deployment_namespace) VALUES (%s)",
            (NAMESPACE,),
        )
    events = [_intent(legacy_dsn, session.session_id, "run") for _ in range(3)]
    for event in reversed(events):
        with psycopg.connect(legacy_dsn) as connection:
            connection.execute(
                """INSERT INTO session_command_pending (
                   deployment_namespace, scope_key, command_id, session_id,
                   accepted_event_id, accepted_sequence, tenant_id, workspace_id, command_kind
                   ) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s)""",
                (
                    NAMESPACE,
                    command_scope_key(SCOPE),
                    event.payload["command_id"],
                    session.session_id,
                    event.event_id,
                    event.sequence,
                    SCOPE.tenant_id,
                    SCOPE.workspace_id,
                    event.payload["kind"],
                ),
            )
    migration_runner.apply_postgres_migrations(legacy_dsn)
    rows = sorted(_rows(legacy_dsn, "session_command_pending"), key=lambda row: row["created_at"])
    assert [row["scope_sequence"] for row in rows] == [1, 2, 3]
    rollout = _rows(legacy_dsn, "command_wakeup_rollouts")[0]
    assert (
        rollout["max_pending_per_scope"],
        rollout["max_pending_control_per_scope"],
        rollout["max_unpublished_outbox"],
        rollout["reserved_control_outbox"],
    ) == (32, 8, 10_000, 64)
    before = _rows(legacy_dsn, "session_command_pending")
    with psycopg.connect(legacy_dsn) as connection:
        with pytest.raises(psycopg.errors.CheckViolation):
            connection.execute(
                """UPDATE command_wakeup_rollouts
                   SET max_unpublished_outbox=1, reserved_control_outbox=1"""
            )
    later = _intent(legacy_dsn, session.session_id, "run")
    with psycopg.connect(legacy_dsn) as connection:
        connection.execute(
            """INSERT INTO session_command_pending (
               deployment_namespace, scope_key, command_id, session_id,
               accepted_event_id, accepted_sequence, tenant_id, workspace_id, command_kind
               ) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s)""",
            (
                NAMESPACE,
                command_scope_key(SCOPE),
                later.payload["command_id"],
                session.session_id,
                later.event_id,
                later.sequence,
                SCOPE.tenant_id,
                SCOPE.workspace_id,
                later.payload["kind"],
            ),
        )
    assert max(row["scope_sequence"] for row in _rows(legacy_dsn, "session_command_pending")) == 4
    before = _rows(legacy_dsn, "session_command_pending")
    migration_runner.apply_postgres_migrations(legacy_dsn)
    assert _rows(legacy_dsn, "session_command_pending") == before


def test_v49_old_writer_trigger_enforces_scope_and_global_capacity(legacy_dsn):
    session = _seed(legacy_dsn)
    events = [_intent(legacy_dsn, session.session_id, "run") for _ in range(3)]
    migration_runner.apply_postgres_migrations(legacy_dsn)
    with psycopg.connect(legacy_dsn) as connection:
        connection.execute(
            """INSERT INTO command_wakeup_rollouts (
               deployment_namespace, admission_enabled, max_pending_per_scope,
               max_unpublished_outbox, reserved_control_outbox
               ) VALUES (%s,TRUE,1,100,0)""",
            (NAMESPACE,),
        )

    def old_insert(event, scope_key, tenant="tenant-a", *, idempotent=False):
        with psycopg.connect(legacy_dsn) as connection:
            connection.execute(
                """INSERT INTO session_command_pending (
                   deployment_namespace, scope_key, command_id, session_id,
                   accepted_event_id, accepted_sequence, tenant_id, workspace_id,
                   origin, command_kind
                   ) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,'live','run')"""
                + (" ON CONFLICT DO NOTHING" if idempotent else ""),
                (
                    NAMESPACE,
                    scope_key,
                    event.payload["command_id"],
                    event.session_id,
                    event.event_id,
                    event.sequence,
                    tenant,
                    SCOPE.workspace_id,
                ),
            )

    old_insert(events[0], command_scope_key(SCOPE))
    with pytest.raises(psycopg.errors.CheckViolation, match="command_scope_capacity"):
        old_insert(events[1], command_scope_key(SCOPE))

    with psycopg.connect(legacy_dsn, row_factory=dict_row) as connection:
        record_command_wakeup_in_transaction(
            connection, NAMESPACE, events[0], is_new_admission=True
        )
    with psycopg.connect(legacy_dsn) as connection:
        connection.execute(
            """UPDATE command_wakeup_rollouts
               SET max_unpublished_outbox=1, reserved_control_outbox=0
               WHERE deployment_namespace=%s""",
            (NAMESPACE,),
        )
        connection.execute(
            """UPDATE broker_outbox SET message_type='zebra.session.command.wrong'
               WHERE deployment_namespace=%s AND operation_id=%s""",
            (NAMESPACE, events[0].payload["command_id"]),
        )
    pending_before = _rows(legacy_dsn, "session_command_pending")
    outbox_before = _rows(legacy_dsn, "broker_outbox")
    with pytest.raises(psycopg.errors.CheckViolation, match="command_outbox_capacity"):
        old_insert(events[0], command_scope_key(SCOPE), idempotent=True)
    assert _rows(legacy_dsn, "session_command_pending") == pending_before
    assert _rows(legacy_dsn, "broker_outbox") == outbox_before

    with psycopg.connect(legacy_dsn) as connection:
        connection.execute(
            """UPDATE broker_outbox SET message_type='zebra.session.command.ready'
               WHERE deployment_namespace=%s AND operation_id=%s""",
            (NAMESPACE, events[0].payload["command_id"]),
        )
    pending_before = _rows(legacy_dsn, "session_command_pending")
    outbox_before = _rows(legacy_dsn, "broker_outbox")
    old_insert(events[0], command_scope_key(SCOPE), idempotent=True)
    assert _rows(legacy_dsn, "session_command_pending") == pending_before
    assert _rows(legacy_dsn, "broker_outbox") == outbox_before
    with pytest.raises(psycopg.errors.CheckViolation, match="command_outbox_capacity"):
        old_insert(events[2], "principal:tenant-c:workspace-a", "tenant-c")
