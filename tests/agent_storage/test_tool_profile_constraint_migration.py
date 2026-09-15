from agent_core.domain.tool_profiles import ToolProfile
from agent_storage.postgres.tool_profile_constraint_migration import (
    TOOL_PROFILE_CONSTRAINT_MIGRATION,
)


def test_workspace_tool_profile_constraint_accepts_every_domain_profile() -> None:
    sql = " ".join(TOOL_PROFILE_CONSTRAINT_MIGRATION.statements)

    assert TOOL_PROFILE_CONSTRAINT_MIGRATION.version == 57
    assert all(f"'{profile.value}'" in sql for profile in ToolProfile)
