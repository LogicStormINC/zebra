"""PostgreSQL v20: mirror the Definition snapshot in workspace projections."""

from agent_storage.postgres.migration_types import Migration

WORKSPACE_DEFINITION_SNAPSHOT_MIGRATION = Migration(
    version=20,
    name="workspace_definition_snapshot_mirror",
    statements=(
        """
        ALTER TABLE workspace_projections
        ADD COLUMN definition_snapshot JSONB CHECK (
            definition_snapshot IS NULL
            OR jsonb_typeof(definition_snapshot) = 'object'
        )
        """,
    ),
)
