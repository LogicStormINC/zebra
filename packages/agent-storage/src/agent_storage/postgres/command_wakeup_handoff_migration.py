"""v38: conservative origin and durable command-to-existing-Lease association."""

from agent_storage.postgres.migration_types import Migration

COMMAND_HANDOFF_MIGRATION = Migration(
    version=38,
    name="command_handoff_receipts_and_inbox",
    statements=(
        """ALTER TABLE session_command_pending ADD COLUMN origin TEXT NOT NULL
           DEFAULT 'historical' CHECK (origin IN ('historical', 'live'))""",
        """CREATE TABLE command_handoff_receipts (
            deployment_namespace TEXT NOT NULL,
            scope_key TEXT NOT NULL,
            command_id UUID NOT NULL,
            accepted_event_id UUID NOT NULL,
            session_id UUID NOT NULL,
            status TEXT NOT NULL CHECK (status IN ('accepted', 'requires_reconciliation')),
            control_plane_epoch UUID,
            fencing_token BIGINT,
            owner_instance_id TEXT,
            created_at TIMESTAMPTZ NOT NULL DEFAULT clock_timestamp(),
            PRIMARY KEY (deployment_namespace, scope_key, command_id),
            UNIQUE (deployment_namespace, accepted_event_id),
            FOREIGN KEY (deployment_namespace, accepted_event_id)
                REFERENCES session_events (deployment_namespace, event_id),
            CHECK ((status = 'accepted' AND control_plane_epoch IS NOT NULL
                    AND fencing_token IS NOT NULL AND fencing_token > 0
                    AND owner_instance_id IS NOT NULL)
                OR (status = 'requires_reconciliation' AND control_plane_epoch IS NULL
                    AND fencing_token IS NULL AND owner_instance_id IS NULL))
        )""",
        """CREATE TABLE broker_command_inbox (
            deployment_namespace TEXT NOT NULL,
            message_id UUID NOT NULL,
            envelope_digest TEXT NOT NULL,
            scope_key TEXT NOT NULL,
            command_id UUID NOT NULL,
            accepted_event_id UUID NOT NULL,
            status TEXT NOT NULL CHECK (status IN ('accepted', 'requires_reconciliation')),
            created_at TIMESTAMPTZ NOT NULL DEFAULT clock_timestamp(),
            PRIMARY KEY (deployment_namespace, message_id),
            FOREIGN KEY (deployment_namespace, scope_key, command_id)
                REFERENCES command_handoff_receipts (deployment_namespace, scope_key, command_id)
        )""",
    ),
)
