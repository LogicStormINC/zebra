"""One-time SQLite derived-cell upgrade; never reads canonical Event bodies."""

import sqlite3

from agent_storage.task_projection_checkpoint_schema import SCHEMA

_CELL_SCHEMA = """CREATE TABLE task_projection_cells_coverage (
    deployment_namespace TEXT NOT NULL, task_id TEXT NOT NULL,
    anchor_key TEXT NOT NULL, projector_version TEXT NOT NULL,
    segment_id TEXT NOT NULL,
    cell_kind TEXT NOT NULL CHECK(cell_kind IN (
        'text_message','text_ended','tool_call','interrupt','run_member','handoff','coverage','standard_v1')),
    cell_key TEXT NOT NULL, task_sequence INTEGER NOT NULL CHECK(task_sequence >= 0),
    value TEXT CHECK(
        cell_kind IN ('text_message','handoff','coverage','standard_v1')
        OR value IS NULL OR value='1'),
    byte_count INTEGER NOT NULL CHECK(byte_count>0),
    PRIMARY KEY(deployment_namespace,task_id,anchor_key,projector_version,
                segment_id,cell_kind,cell_key,task_sequence)
)"""
_COLUMNS = (
    "deployment_namespace,task_id,anchor_key,projector_version,segment_id,"
    "cell_kind,cell_key,task_sequence,value,byte_count"
)
COVERAGE_PRIVACY = """((event_type='task_prepared'
    AND json_type(payload,'$.coverage_admission') IS NOT NULL)
    OR event_type IN ('coverage_manifest_committed','coverage_batch_accepted',
                     'coverage_run_cancelled','coverage_report_certified'))"""


def initialize_task_replay_privacy(connection: sqlite3.Connection) -> None:
    """Install native privacy coordinates without unrelated checkpoint tables."""
    # Isolated schema-upgrade checks need no canonical Event table. Native
    # composition installs this source-maintained index after Task columns.
    if connection.execute(
        "SELECT 1 FROM sqlite_schema WHERE type='table' AND name='session_events'"
    ).fetchone():
        installed = connection.execute(
            "SELECT 1 FROM sqlite_schema WHERE name='task_replay_coverage_privacy'"
        ).fetchone()
        connection.execute(
            "CREATE TABLE IF NOT EXISTS task_replay_coverage_privacy "
            "(event_id TEXT PRIMARY KEY,task_id TEXT NOT NULL,"
            "task_sequence INTEGER NOT NULL CHECK(task_sequence>=0))"
        )
        old_index = connection.execute(
            "SELECT tbl_name FROM sqlite_schema WHERE name='session_events_coverage_privacy'"
        ).fetchone()
        if old_index and old_index[0] == "session_events":
            connection.execute("DROP INDEX session_events_coverage_privacy")
        connection.execute(
            "CREATE INDEX IF NOT EXISTS session_events_coverage_privacy "
            "ON task_replay_coverage_privacy(task_id,task_sequence)"
        )
        connection.execute(
            "CREATE TRIGGER IF NOT EXISTS coverage_privacy_insert_guard "
            "BEFORE INSERT ON task_replay_coverage_privacy WHEN NOT EXISTS("
            "SELECT 1 FROM session_events WHERE event_id=NEW.event_id "
            "AND task_id=NEW.task_id AND task_sequence=NEW.task_sequence "
            f"AND {COVERAGE_PRIVACY}) BEGIN "
            "SELECT RAISE(ABORT,'privacy metadata must match its immutable source'); END"
        )
        for operation in ("UPDATE", "DELETE"):
            connection.execute(
                f"CREATE TRIGGER IF NOT EXISTS coverage_privacy_{operation.lower()}_guard "
                f"BEFORE {operation} ON task_replay_coverage_privacy BEGIN "
                "SELECT RAISE(ABORT,'privacy metadata is immutable'); END"
            )
        for name, operation in (
            ("insert", "INSERT"),
            ("assign", "UPDATE OF task_id,task_sequence"),
        ):
            connection.execute(
                f"CREATE TRIGGER IF NOT EXISTS coverage_privacy_source_{name} "
                f"AFTER {operation} ON session_events BEGIN "
                "INSERT OR IGNORE INTO task_replay_coverage_privacy "
                "SELECT event_id,task_id,task_sequence FROM session_events "
                "WHERE event_id=NEW.event_id AND task_id IS NOT NULL "
                f"AND task_sequence IS NOT NULL AND {COVERAGE_PRIVACY}; END"
            )
        if not installed:
            # One-time source-owned locator backfill, never a hot body read.
            connection.execute(
                "INSERT INTO task_replay_coverage_privacy "
                "SELECT event_id,task_id,task_sequence FROM session_events "
                "WHERE task_id IS NOT NULL AND task_sequence IS NOT NULL "
                f"AND {COVERAGE_PRIVACY}"
            )


def initialize_task_projection_checkpoints(connection: sqlite3.Connection) -> None:
    connection.executescript(SCHEMA)
    # ponytail: SQLite cannot ALTER a CHECK. One upgrade copies derived cells,
    # not history; very large local projections need explicit offline migration.
    connection.execute("BEGIN IMMEDIATE")
    try:
        schema = connection.execute(
            "SELECT sql FROM sqlite_schema WHERE type='table' AND name='task_projection_cells'"
        ).fetchone()[0]
        initialize_task_replay_privacy(connection)
        if "'standard_v1'" not in schema:
            dependent = connection.execute(
                "SELECT sql FROM sqlite_schema WHERE tbl_name='task_projection_cells' "
                "AND type IN ('index','trigger') AND sql IS NOT NULL ORDER BY type,name"
            ).fetchall()
            connection.execute(_CELL_SCHEMA)
            connection.execute(
                f"INSERT INTO task_projection_cells_coverage({_COLUMNS}) "
                f"SELECT {_COLUMNS} FROM task_projection_cells"
            )
            connection.execute("DROP TABLE task_projection_cells")
            connection.execute(
                "ALTER TABLE task_projection_cells_coverage RENAME TO task_projection_cells"
            )
            for row in dependent:
                connection.execute(row[0])
        connection.commit()
    except BaseException:
        connection.rollback()
        raise
