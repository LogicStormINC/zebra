"""PostgreSQL v22: typed enforcement mode on agent release records."""

from agent_storage.postgres.migration_types import Migration

AGENT_RELEASE_ENFORCEMENT_MIGRATION = Migration(
    version=22,
    name="agent_release_enforcement_mode",
    statements=(
        """
        ALTER TABLE agent_release_records
        ADD COLUMN enforcement_mode TEXT NOT NULL DEFAULT 'safe-boundary' CHECK (
            enforcement_mode IN ('safe-boundary', 'immediate')
        ),
        ADD CONSTRAINT agent_release_published_safe_boundary CHECK (
            status != 'published' OR enforcement_mode = 'safe-boundary'
        )
        """,
    ),
)
