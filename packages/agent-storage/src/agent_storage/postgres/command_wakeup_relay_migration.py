"""PostgreSQL v37: expired relay ownership discovery, separate from execution."""

from agent_storage.postgres.migration_types import Migration

COMMAND_RELAY_MIGRATION = Migration(
    version=37,
    name="broker_outbox_expired_publishing_index",
    statements=(
        """CREATE INDEX broker_outbox_expired_publishing
           ON broker_outbox (deployment_namespace, lease_expires_at, message_id)
           WHERE status = 'publishing'""",
    ),
)
