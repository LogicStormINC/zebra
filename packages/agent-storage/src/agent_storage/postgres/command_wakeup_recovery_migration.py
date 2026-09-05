"""v40: bounded recovery approval and immutable prior execution-attempt evidence."""

from agent_storage.postgres.migration_types import Migration

COMMAND_RECOVERY_MIGRATION = Migration(
    version=40, name="command_recovery_generations",
    statements=(
        """ALTER TABLE session_command_pending
           ADD COLUMN current_generation BIGINT NOT NULL DEFAULT 0 CHECK(current_generation >= 0),
           ADD COLUMN recovery_due_at TIMESTAMPTZ NOT NULL
               DEFAULT (clock_timestamp() + interval '60 seconds'),
           ADD COLUMN recovery_code TEXT""",
        """ALTER TABLE command_handoff_receipts
           ADD COLUMN wake_generation BIGINT NOT NULL DEFAULT 0 CHECK(wake_generation >= 0)""",
        """CREATE INDEX command_recovery_due ON session_command_pending
           (deployment_namespace, scope_key, recovery_due_at, accepted_event_id)
           WHERE status = 'pending' AND origin = 'live'""",
        """CREATE TABLE command_recovery_attempts (
           deployment_namespace TEXT NOT NULL,
           accepted_event_id UUID NOT NULL,
           wake_generation BIGINT NOT NULL CHECK(wake_generation > 0),
           previous_message_id UUID NOT NULL,
           message_id UUID NOT NULL,
           approved_stream_sequence BIGINT NOT NULL CHECK(approved_stream_sequence > 0),
           reason TEXT NOT NULL CHECK(reason IN ('published_no_handoff', 'expired_unstarted')),
           previous_receipt JSONB,
           approved_at TIMESTAMPTZ NOT NULL DEFAULT clock_timestamp(),
           PRIMARY KEY(deployment_namespace, accepted_event_id, wake_generation),
           FOREIGN KEY(deployment_namespace, accepted_event_id)
               REFERENCES session_events(deployment_namespace, event_id),
           FOREIGN KEY(deployment_namespace, previous_message_id)
               REFERENCES broker_outbox(deployment_namespace, message_id),
           FOREIGN KEY(deployment_namespace, message_id)
               REFERENCES broker_outbox(deployment_namespace, message_id)
        )""",
    ),
)
