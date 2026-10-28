"""Recognize exact approval wakeups without opening a second Run."""

from agent_storage.postgres.migration_types import Migration
from agent_storage.postgres.task_replay_scalar_header_migration import (
    TASK_REPLAY_SCALAR_HEADER_MIGRATION,
)

# Reuse the immutable v66 definition; only extend the allowed internal key family.
APPROVAL_CONTINUATION_MIGRATION = Migration(
    version=108,
    name="approval_internal_continuation",
    statements=(
        TASK_REPLAY_SCALAR_HEADER_MIGRATION.statements[1]
        .replace("CREATE FUNCTION", "CREATE OR REPLACE FUNCTION", 1)
        .replace(
            "OR NEW.payload->>'idempotency_key' LIKE 'client-effect-resume:%'",
            "OR NEW.payload->>'idempotency_key' LIKE 'client-effect-resume:%' "
            "OR NEW.payload->>'idempotency_key' LIKE 'approval-resume:%'",
        ),
    ),
)
