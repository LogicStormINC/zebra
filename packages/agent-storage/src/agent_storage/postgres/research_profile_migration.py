"""Migration v29: accept the read-only research child tool profile."""

from agent_storage.postgres.migration_types import Migration

RESEARCH_TOOL_PROFILE_MIGRATION = Migration(
    version=29,
    name="research_tool_profile",
    statements=(
        """
        ALTER TABLE workspace_projections
            DROP CONSTRAINT workspace_projections_tool_profile_check
        """,
        """
        ALTER TABLE workspace_projections
            ADD CONSTRAINT workspace_projections_tool_profile_check
            CHECK (tool_profile IN ('general', 'coding', 'research'))
        """,
    ),
)
