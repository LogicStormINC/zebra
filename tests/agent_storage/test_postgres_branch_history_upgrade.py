"""Real SQL upgrades preserve either published ledger and original P5 proof."""

from concurrent.futures import ThreadPoolExecutor
from unittest.mock import patch
from uuid import uuid4

import psycopg
import pytest
from agent_storage import apply_postgres_migrations, bootstrap_control_plane_epoch
from agent_storage.postgres.migration_runner import require_current_schema
from agent_storage.postgres.migration_types import PostgresMigrationError
from agent_storage.postgres.migrations import MIGRATIONS
from agent_storage.postgres.runtime_gate_migration import RUNTIME_GATE_MIGRATION
from agent_storage.postgres.runtime_gate_termination_migration import (
    RUNTIME_GATE_TERMINATION_MIGRATION,
)
from agent_storage.postgres.worker_capability import _require_schema
from psycopg import sql
from psycopg.conninfo import make_conninfo
from psycopg.rows import dict_row
from zebra_agent_worker.command_process_state import command_cutover_state


@pytest.mark.parametrize("p5_history", [False, True])
def test_upgrade_keeps_original_ledger_and_gate_proof(postgres_dsn, p5_history):
    schema = f"test_p5_branch_merge_{uuid4().hex}"
    with psycopg.connect(postgres_dsn) as connection:
        connection.execute(sql.SQL("CREATE SCHEMA {}").format(sql.Identifier(schema)))
    dsn = make_conninfo(postgres_dsn, options=f"-c search_path={schema}")
    try:
        old = tuple(m for m in MIGRATIONS if m.version <= (114 if p5_history else 117))
        if p5_history:
            old += (RUNTIME_GATE_MIGRATION, RUNTIME_GATE_TERMINATION_MIGRATION)
        with patch(
            "agent_storage.postgres.migration_runner.migration_history_plan", return_value=old
        ):
            apply_postgres_migrations(dsn)
        with psycopg.connect(dsn) as connection:
            before = connection.execute(
                "SELECT * FROM zebra_schema_migrations ORDER BY version"
            ).fetchall()
        namespace = f"merge-{uuid4().hex}"
        bootstrap_control_plane_epoch(dsn, deployment_namespace=namespace)
        proof_before = None
        if p5_history:
            with psycopg.connect(dsn) as connection:
                connection.execute(
                    """INSERT INTO runtime_gate_terminations VALUES
                    (%s,%s,%s,'{"original":"intent"}',%s,'{"state":"unknown"}',now())""",
                    (namespace, uuid4(), uuid4(), "a" * 64),
                )
                proof_before = connection.execute(
                    "SELECT * FROM runtime_gate_terminations"
                ).fetchall()
        with pytest.raises(PostgresMigrationError):
            require_current_schema(dsn)
        with ThreadPoolExecutor(max_workers=2) as executor:
            tuple(executor.map(apply_postgres_migrations, (dsn, dsn)))
        require_current_schema(dsn)
        # Schema acceptance must not itself grant command admission/cutover.
        with pytest.raises(ValueError, match="explicit operator cutover"):
            command_cutover_state(dsn, namespace, require_ready=True)
        with psycopg.connect(dsn, row_factory=dict_row) as connection:
            _require_schema(connection)
        with psycopg.connect(dsn) as connection:
            after = connection.execute(
                "SELECT * FROM zebra_schema_migrations ORDER BY version"
            ).fetchall()
            assert all(row in after for row in before)
            assert len(after) == len(MIGRATIONS)
            if p5_history:
                assert (
                    connection.execute("SELECT * FROM runtime_gate_terminations").fetchall()
                    == proof_before
                )
            connection.execute(
                "UPDATE zebra_schema_migrations SET checksum=%s WHERE version=115", ("0" * 64,)
            )
        with pytest.raises(ValueError, match="complete verified schema"):
            command_cutover_state(dsn, namespace, require_ready=True)
        with pytest.raises(PostgresMigrationError):
            apply_postgres_migrations(dsn)
        with pytest.raises(PostgresMigrationError):
            require_current_schema(dsn)
    finally:
        with psycopg.connect(postgres_dsn) as connection:
            connection.execute(sql.SQL("DROP SCHEMA {} CASCADE").format(sql.Identifier(schema)))
