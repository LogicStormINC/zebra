"""Migrate an isolated ERP clone and compare every original table/column.

Run only in the frozen candidate image; never starts an API, Worker or scheduler.
"""

import hashlib
import json
import os
from pathlib import Path

import psycopg
from agent_storage.postgres.migration_runner import (
    apply_postgres_migrations,
    require_current_schema,
)
from agent_storage.postgres.migrations import MIGRATIONS
from psycopg import sql
from psycopg.conninfo import conninfo_to_dict


def require_isolated(dsn):
    parts = conninfo_to_dict(dsn)
    if (
        parts.get("dbname") != "erp_agent_capability_qa_20261028"
        or parts.get("host") != "127.0.0.1"
        or parts.get("port", "5432") != "5432"
    ):
        raise ValueError("Only the fixed isolated loopback clone is permitted")


def columns(connection):
    rows = connection.execute("""SELECT c.relname,a.attname FROM pg_class c
        JOIN pg_namespace n ON n.oid=c.relnamespace
        JOIN pg_attribute a ON a.attrelid=c.oid
        WHERE n.nspname='public' AND c.relkind IN ('r','p')
          AND a.attnum>0 AND NOT a.attisdropped ORDER BY c.relname,a.attnum""").fetchall()
    result = {}
    for table, column in rows:
        result.setdefault(table, []).append(column)
    return result


def inventory(connection, definitions, *, ledger_ceiling=None):
    result = {}
    for table, names in definitions.items():
        statement = sql.SQL("""SELECT encode(sha256(convert_to(row_to_json(t)::text,
            'UTF8')),'hex') AS digest FROM (SELECT {} FROM public.{}) t ORDER BY 1""").format(
            sql.SQL(",").join(map(sql.Identifier, names)), sql.Identifier(table)
        )
        if table == "zebra_schema_migrations" and ledger_ceiling is not None:
            statement = sql.SQL(
                "SELECT encode(sha256(convert_to(row_to_json(t)::text,'UTF8')),'hex') "
                "FROM (SELECT {} FROM public.{} WHERE version <= %s) t ORDER BY 1"
            ).format(sql.SQL(",").join(map(sql.Identifier, names)), sql.Identifier(table))
        digest, count = hashlib.sha256(), 0
        with connection.cursor(name="capability_inventory") as cursor:
            cursor.execute(
                statement,
                (ledger_ceiling,)
                if table == "zebra_schema_migrations" and ledger_ceiling is not None
                else None,
            )
            for row in cursor:
                count += 1
                if count > 250000:
                    raise ValueError("Clone inventory row budget exceeded")
                digest.update(row[0].encode("ascii") + b"\n")
        result[table] = {"count": count, "sha256": digest.hexdigest()}
    return result


def read_inventory(dsn, definitions=None, *, ledger_ceiling=None):
    with psycopg.connect(dsn) as connection:
        connection.execute("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ, READ ONLY")
        definitions = columns(connection) if definitions is None else definitions
        return definitions, inventory(connection, definitions, ledger_ceiling=ledger_ceiling)


def main():
    dsn = os.environ["ERP_CAPABILITY_QA_DSN"]
    require_isolated(dsn)
    output = Path(os.environ["ERP_CAPABILITY_QA_OUTPUT"])
    if output.exists():
        raise ValueError("Refusing to replace previous acceptance evidence")
    with psycopg.connect(dsn) as connection:
        connection.execute("SET TRANSACTION READ ONLY")
        ledger = connection.execute(
            "SELECT version,name,checksum FROM zebra_schema_migrations"
        ).fetchall()
        server = connection.execute("SHOW server_version").fetchone()[0]
    expected = {(m.version, m.name, m.checksum) for m in MIGRATIONS if m.version <= 105}
    if set(ledger) != expected:
        raise ValueError("Clone is not the exact original Native105 ledger")
    original_columns, before = read_inventory(dsn, ledger_ceiling=105)
    print(json.dumps({"stage": "before", "tables": len(before), "server": server}), flush=True)
    apply_postgres_migrations(dsn)
    require_current_schema(dsn)
    _, after = read_inventory(dsn, original_columns, ledger_ceiling=105)
    changed = [table for table in before if before[table] != after[table]]
    all_columns, all_before = read_inventory(dsn)
    apply_postgres_migrations(dsn)
    _, all_after = read_inventory(dsn, all_columns)
    result = {
        "source_version": 105,
        "target_version": max(m.version for m in MIGRATIONS),
        "server_version": server,
        "original_tables": len(before),
        "target_tables": len(all_columns),
        "changed_original_tables": changed,
        "migration_idempotent": all_before == all_after,
        "before": before,
        "after_original_columns": after,
        "model_calls": 0,
        "search_calls": 0,
        "worker_started": False,
    }
    output.write_text(json.dumps(result, indent=2) + "\n")
    output.chmod(0o600)
    if changed or all_before != all_after:
        raise ValueError(
            "Original data or migration idempotence differs; inspect retained evidence"
        )
    print(
        json.dumps(
            {
                key: value
                for key, value in result.items()
                if key not in {"before", "after_original_columns"}
            }
        ),
        flush=True,
    )


if __name__ == "__main__":
    main()
