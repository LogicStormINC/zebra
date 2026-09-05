"""v45: sanitized diagnostic receipts, independent of canonical command authority."""
from agent_storage.postgres.migration_types import Migration

COMMAND_QUARANTINE_MIGRATION = Migration(
    version=45, name="command_delivery_quarantine",
    statements=(
        """CREATE TABLE command_delivery_rejections (
           deployment_namespace TEXT NOT NULL, consumer_role TEXT NOT NULL,
           rejection_id UUID NOT NULL, body_digest TEXT NOT NULL
             CHECK(body_digest ~ '^[0-9a-f]{64}$'), byte_count BIGINT NOT NULL CHECK(byte_count>=0),
           error_code TEXT NOT NULL CHECK(error_code IN
             ('invalid_broker_envelope','broker_hint_conflict')),
           created_at_ms BIGINT NOT NULL
             DEFAULT (extract(epoch FROM clock_timestamp())*1000)::bigint,
           status TEXT NOT NULL DEFAULT 'pending'
             CHECK(status IN ('pending','publishing','published')),
           available_at TIMESTAMPTZ NOT NULL DEFAULT clock_timestamp(),
           relay_owner TEXT, relay_fence BIGINT NOT NULL DEFAULT 0,
           lease_expires_at TIMESTAMPTZ, publish_attempts BIGINT NOT NULL DEFAULT 0,
           published_at TIMESTAMPTZ,
           PRIMARY KEY(deployment_namespace, rejection_id),
           UNIQUE(deployment_namespace, consumer_role, body_digest, error_code)
        )""",
        """CREATE INDEX command_rejection_due ON command_delivery_rejections
           (deployment_namespace, consumer_role, available_at, rejection_id)
           WHERE status='pending'""",
        """CREATE INDEX command_rejection_expired ON command_delivery_rejections
           (deployment_namespace, consumer_role, lease_expires_at, rejection_id)
           WHERE status='publishing'""",
    ),
)
