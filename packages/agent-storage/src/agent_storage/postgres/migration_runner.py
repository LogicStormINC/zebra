"""Checksum-verified PostgreSQL migration execution."""

import psycopg

from agent_storage.postgres.migration_types import PostgresMigrationError
from agent_storage.postgres.migrations import MIGRATIONS

_MIGRATION_LOCK_ID = 9_187_330_641


def apply_postgres_migrations(dsn: str) -> None:
    """Apply known migrations under one transaction-scoped advisory lock."""
    with psycopg.connect(dsn) as connection:
        connection.execute("SELECT pg_advisory_xact_lock(%s)", (_MIGRATION_LOCK_ID,))
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS zebra_schema_migrations (
                version BIGINT PRIMARY KEY,
                name TEXT NOT NULL,
                checksum TEXT NOT NULL,
                applied_at TIMESTAMPTZ NOT NULL DEFAULT now()
            )
            """
        )
        applied = {
            row[0]: (row[1], row[2])
            for row in connection.execute(
                "SELECT version, name, checksum FROM zebra_schema_migrations"
            ).fetchall()
        }
        known_versions = {migration.version for migration in MIGRATIONS}
        unknown_versions = sorted(set(applied) - known_versions)
        if unknown_versions:
            raise PostgresMigrationError(
                f"database has unknown migration versions: {unknown_versions}"
            )
        for migration in MIGRATIONS:
            existing = applied.get(migration.version)
            if existing is not None:
                if existing != (migration.name, migration.checksum):
                    raise PostgresMigrationError(
                        f"migration {migration.version} checksum or name does not match"
                    )
                continue
            for statement in migration.statements:
                connection.execute(statement)
            connection.execute(
                """
                INSERT INTO zebra_schema_migrations (version, name, checksum)
                VALUES (%s, %s, %s)
                """,
                (migration.version, migration.name, migration.checksum),
            )
