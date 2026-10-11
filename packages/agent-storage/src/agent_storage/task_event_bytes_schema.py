"""SQLite source-owned v2 byte bounds, never computed by page observers."""

import sqlite3

from agent_storage.database import ensure_column

# Fixed UUIDs, bounded timestamps/enums and three int64 coordinates fit in 768
# bytes; variable header strings use their worst-case JSON escaping expansion.
# A legacy JSON real token (1e9) can grow on Python float serialization. A
# binary64 repr needs at most 24 bytes; integers and JSON strings cannot grow.
# SQLite maps legacy NaN to JSON null; typed output grows from 3 to 4 bytes.
# Charge one byte per null as well, in the same native tree traversal.
BYTE_BOUND = (
    "length(CAST(payload AS BLOB)) + 768 + "
    "(SELECT sum(CASE type WHEN 'real' THEN 24 WHEN 'null' THEN 1 ELSE 0 END) "
    "FROM json_tree(payload)) + 6*("
    "length(CAST(COALESCE(idempotency_key,'') AS BLOB)) +"
    "length(CAST(COALESCE(policy_version,'') AS BLOB)) +"
    "length(CAST(COALESCE(model_profile,'') AS BLOB)))"
)
NEW_BYTE_BOUND = (
    "length(CAST(NEW.payload AS BLOB)) + 768 + "
    "(SELECT sum(CASE type WHEN 'real' THEN 24 WHEN 'null' THEN 1 ELSE 0 END) "
    "FROM json_tree(NEW.payload)) + 6*("
    "length(CAST(COALESCE(NEW.idempotency_key,'') AS BLOB)) +"
    "length(CAST(COALESCE(NEW.policy_version,'') AS BLOB)) +"
    "length(CAST(COALESCE(NEW.model_profile,'') AS BLOB)))"
)
BYTE_STATEMENTS = (
    f"""CREATE TRIGGER IF NOT EXISTS session_events_byte_bound_insert
AFTER INSERT ON session_events BEGIN
  UPDATE session_events SET event_bytes_bound={BYTE_BOUND} WHERE event_id=NEW.event_id;
END""",
    f"""CREATE TRIGGER IF NOT EXISTS session_events_byte_bound_update
AFTER UPDATE OF payload,idempotency_key,policy_version,model_profile ON session_events BEGIN
  UPDATE session_events SET event_bytes_bound={BYTE_BOUND} WHERE event_id=NEW.event_id;
END""",
    f"""CREATE TRIGGER IF NOT EXISTS session_events_byte_bound_guard
BEFORE UPDATE OF event_bytes_bound ON session_events
WHEN NEW.event_bytes_bound IS NOT ({NEW_BYTE_BOUND})
BEGIN SELECT RAISE(ABORT,'Event byte bound must match its source'); END""",
)
BYTE_SCHEMA = ";\n".join(BYTE_STATEMENTS) + ";"


def initialize_event_byte_bounds(connection: sqlite3.Connection) -> None:
    """Retire untrusted v1 scalars with metadata-only DDL, atomically once.

    Existing bodies stay untouched. NULL v2 bounds make pages fail closed until
    the operator's bounded adoption/repair visits each source row. No CHECK is
    added here: SQLite would validate it against every historical row.
    """
    with connection:
        connection.execute("BEGIN IMMEDIATE")
        columns = {row[1] for row in connection.execute("PRAGMA table_info(session_events)")}
        if "event_bytes_bound_v1" not in columns:
            if "event_bytes_bound" in columns:
                connection.execute(
                    "ALTER TABLE session_events RENAME COLUMN event_bytes_bound "
                    "TO event_bytes_bound_v1"
                )
            else:
                ensure_column(connection, "session_events", "event_bytes_bound_v1", "INTEGER")
            for name in ("insert", "update", "guard"):
                connection.execute(f"DROP TRIGGER IF EXISTS session_events_byte_bound_{name}")
        ensure_column(connection, "session_events", "event_bytes_bound", "INTEGER")
        for statement in BYTE_STATEMENTS:
            connection.execute(statement)
