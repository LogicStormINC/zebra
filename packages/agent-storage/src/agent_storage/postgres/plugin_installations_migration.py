"""PostgreSQL v105: plugin facts reuse exact-scope immutable extension revisions."""

from agent_storage.postgres.migration_types import Migration

PLUGIN_INSTALLATIONS_MIGRATION = Migration(
    version=105,
    name="scoped_plugin_installations",
    statements=tuple(
        statement
        for table in ("extension_configurations", "extension_configuration_revisions")
        for statement in (
            f"ALTER TABLE {table} DROP CONSTRAINT {table}_kind_check",
            f"ALTER TABLE {table} ADD CONSTRAINT {table}_kind_check "
            "CHECK (kind IN ('skill', 'mcp', 'plugin'))",
        )
    ),
)
