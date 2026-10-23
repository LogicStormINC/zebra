"""Forward-only trusted approval wakeups; no issued migration or Event/header rewrite."""

from agent_storage.postgres.migration_types import Migration
from agent_storage.postgres.task_replay_scalar_header_migration import (
    TASK_REPLAY_SCALAR_HEADER_MIGRATION,
)

APPROVAL_RESUME_MIGRATION = Migration(
    version=113,
    name="approval_resume_replay_headers",
    statements=(
        TASK_REPLAY_SCALAR_HEADER_MIGRATION.statements[1]
        .replace("CREATE FUNCTION", "CREATE OR REPLACE FUNCTION", 1)
        .replace(
            "OR NEW.payload->>'idempotency_key' LIKE 'client-effect-resume:%'",
            "OR NEW.payload->>'idempotency_key' LIKE 'client-effect-resume:%' "
            "OR NEW.payload->>'idempotency_key' LIKE 'approval-resume:%'",
            1,
        ),
    ),
)
