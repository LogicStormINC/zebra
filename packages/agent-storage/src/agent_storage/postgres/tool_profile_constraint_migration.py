"""PostgreSQL v57: accept every current ToolProfile value."""

from agent_storage.postgres.migration_types import Migration

TOOL_PROFILE_CONSTRAINT_MIGRATION = Migration(
    version=57,
    name="complete_workspace_tool_profiles",
    statements=(
        """
        ALTER TABLE workspace_projections
            DROP CONSTRAINT workspace_projections_tool_profile_check
        """,
        """
        ALTER TABLE workspace_projections
            ADD CONSTRAINT workspace_projections_tool_profile_check
            CHECK (tool_profile IN (
                'general', 'coding', 'research', 'research_coordinator'
            ))
        """,
    ),
)
