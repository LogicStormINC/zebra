"""PostgreSQL v35: opt-in derived command discovery and Broker Outbox."""

from agent_storage.postgres.migration_types import Migration

COMMAND_WAKEUP_MIGRATION = Migration(
    version=35,
    name="command_pending_and_broker_outbox",
    statements=(
        """
        CREATE TABLE command_wakeup_rollouts (
            deployment_namespace TEXT PRIMARY KEY,
            admission_enabled BOOLEAN NOT NULL DEFAULT FALSE
        )
        """,
        """
        CREATE TABLE session_command_pending (
            deployment_namespace TEXT NOT NULL,
            scope_key TEXT NOT NULL,
            command_id UUID NOT NULL,
            session_id UUID NOT NULL,
            accepted_event_id UUID NOT NULL,
            accepted_sequence BIGINT NOT NULL CHECK (accepted_sequence > 0),
            tenant_id TEXT NOT NULL,
            workspace_id TEXT NOT NULL,
            status TEXT NOT NULL DEFAULT 'pending'
                CHECK (status IN ('pending', 'done', 'cancelled', 'dead')),
            created_at TIMESTAMPTZ NOT NULL DEFAULT clock_timestamp(),
            PRIMARY KEY (deployment_namespace, scope_key, command_id),
            UNIQUE (deployment_namespace, accepted_event_id),
            FOREIGN KEY (deployment_namespace, accepted_event_id)
                REFERENCES session_events (deployment_namespace, event_id)
        )
        """,
        """
        CREATE INDEX session_command_pending_discovery
        ON session_command_pending (
            deployment_namespace, scope_key, created_at, accepted_event_id
        ) WHERE status = 'pending'
        """,
        """
        CREATE TABLE broker_outbox (
            deployment_namespace TEXT NOT NULL,
            message_id UUID NOT NULL,
            scope_key TEXT NOT NULL,
            message_type TEXT NOT NULL,
            schema_version INTEGER NOT NULL CHECK (schema_version = 1),
            aggregate_id UUID NOT NULL,
            operation_id UUID NOT NULL,
            wake_generation BIGINT NOT NULL CHECK (wake_generation >= 0),
            envelope_json JSONB NOT NULL,
            envelope_digest TEXT NOT NULL CHECK (envelope_digest ~ '^[0-9a-f]{64}$'),
            status TEXT NOT NULL DEFAULT 'pending'
                CHECK (status IN ('pending', 'publishing', 'published', 'dead')),
            available_at TIMESTAMPTZ NOT NULL DEFAULT clock_timestamp(),
            publish_attempts INTEGER NOT NULL DEFAULT 0 CHECK (publish_attempts >= 0),
            relay_owner TEXT,
            relay_fence BIGINT NOT NULL DEFAULT 0 CHECK (relay_fence >= 0),
            lease_expires_at TIMESTAMPTZ,
            published_at TIMESTAMPTZ,
            last_error_code TEXT,
            created_at TIMESTAMPTZ NOT NULL DEFAULT clock_timestamp(),
            PRIMARY KEY (deployment_namespace, message_id),
            UNIQUE (deployment_namespace, scope_key, message_type, operation_id, wake_generation)
        )
        """,
        """
        CREATE INDEX broker_outbox_pending_publish
        ON broker_outbox (deployment_namespace, available_at, message_id)
        WHERE status = 'pending'
        """,
    ),
)
