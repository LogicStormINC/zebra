"""v86: additive, opt-in continuation qualification on the native process lease."""

from agent_storage.postgres.migration_types import Migration

WORKER_CONTINUATION_MIGRATION = Migration(
    version=86,
    name="worker_continuation_qualification",
    statements=(
        """ALTER TABLE worker_process_capabilities ADD COLUMN continuation_digest TEXT
           CHECK (continuation_digest ~ '^[0-9a-f]{64}$')""",
    ),
)
