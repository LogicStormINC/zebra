from agent_core.domain.tool_profiles import ToolProfile
from agent_storage.postgres.research_web_profile_migration import RESEARCH_WEB_PROFILE_MIGRATION
from agent_storage.postgres.tool_profile_constraint_migration import (
    TOOL_PROFILE_CONSTRAINT_MIGRATION,
)


def test_workspace_tool_profile_constraint_accepts_every_domain_profile() -> None:
    sql = " ".join(RESEARCH_WEB_PROFILE_MIGRATION.statements)

    assert TOOL_PROFILE_CONSTRAINT_MIGRATION.version == 57
    assert RESEARCH_WEB_PROFILE_MIGRATION.version == 104
    assert all(f"'{profile.value}'" in sql for profile in ToolProfile)
