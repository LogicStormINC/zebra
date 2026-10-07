"""Latest additive migrations kept separate from the primary catalog."""

from agent_storage.postgres.coverage_migration import COVERAGE_MIGRATION
from agent_storage.postgres.full_gateway_migration import FULL_GATEWAY_MIGRATION
from agent_storage.postgres.task_schedule_migration import TASK_SCHEDULE_MIGRATION
from agent_storage.postgres.tool_profile_constraint_migration import (
    TOOL_PROFILE_CONSTRAINT_MIGRATION,
)
from agent_storage.postgres.user_personalization_migration import USER_PERSONALIZATION_MIGRATION

LATEST_MIGRATIONS = (
    TOOL_PROFILE_CONSTRAINT_MIGRATION,
    TASK_SCHEDULE_MIGRATION,
    USER_PERSONALIZATION_MIGRATION,
    FULL_GATEWAY_MIGRATION,
    COVERAGE_MIGRATION,
)
