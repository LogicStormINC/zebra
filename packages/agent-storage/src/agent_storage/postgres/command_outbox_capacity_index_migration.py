"""Index the unpublished rows counted by command admission."""

from agent_storage.postgres.migration_types import Migration

COMMAND_OUTBOX_CAPACITY_INDEX_MIGRATION = Migration(
    version=125,
    name="command_outbox_unpublished_capacity_index",
    statements=(
        """CREATE INDEX broker_outbox_unpublished_capacity
           ON broker_outbox (deployment_namespace)
           WHERE status IN ('pending','publishing')""",
    ),
)
