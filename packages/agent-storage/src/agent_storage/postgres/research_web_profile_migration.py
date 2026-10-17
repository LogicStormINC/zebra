"""PostgreSQL v104: search-only researcher profile; existing rows unchanged."""

from agent_storage.postgres.migration_types import Migration

RESEARCH_WEB_PROFILE_MIGRATION = Migration(
    version=104,
    name="research_web_tool_profile",
    statements=(
        "ALTER TABLE workspace_projections "
        "DROP CONSTRAINT workspace_projections_tool_profile_check",
        """
        ALTER TABLE workspace_projections
            ADD CONSTRAINT workspace_projections_tool_profile_check
            CHECK (tool_profile IN (
                'general', 'coding', 'research', 'research_coordinator', 'research_web'
            ))
        """,
    ),
)
