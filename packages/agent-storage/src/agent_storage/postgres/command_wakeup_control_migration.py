"""v42: independent control outcome, Inbox and durable runtime cleanup obligation."""

from agent_storage.postgres.migration_types import Migration

COMMAND_CONTROL_MIGRATION = Migration(
    version=42, name="command_control_outcomes",
    statements=(
        """CREATE TABLE command_control_receipts (
           deployment_namespace TEXT NOT NULL, accepted_event_id UUID NOT NULL,
           scope_key TEXT NOT NULL, command_id UUID NOT NULL, session_id UUID NOT NULL,
           kind TEXT NOT NULL CHECK(kind IN ('cancel','stop','suspend')),
           outcome TEXT NOT NULL CHECK(outcome IN
               ('cancelled','terminal_noop','unsupported','requires_reconciliation')),
           wake_generation BIGINT NOT NULL CHECK(wake_generation >= 0),
           terminal_event_id UUID, revoked_epoch UUID, revoked_token BIGINT, revoked_owner TEXT,
           created_at TIMESTAMPTZ NOT NULL DEFAULT clock_timestamp(),
           PRIMARY KEY(deployment_namespace, accepted_event_id),
           UNIQUE(deployment_namespace, scope_key, command_id),
           FOREIGN KEY(deployment_namespace, accepted_event_id)
               REFERENCES session_events(deployment_namespace, event_id),
           FOREIGN KEY(deployment_namespace, terminal_event_id)
               REFERENCES session_events(deployment_namespace, event_id)
        )""",
        """CREATE TABLE broker_control_inbox (
           deployment_namespace TEXT NOT NULL, message_id UUID NOT NULL,
           accepted_event_id UUID NOT NULL, envelope_digest TEXT NOT NULL,
           scope_key TEXT NOT NULL, command_id UUID NOT NULL,
           created_at TIMESTAMPTZ NOT NULL DEFAULT clock_timestamp(),
           PRIMARY KEY(deployment_namespace, message_id),
           FOREIGN KEY(deployment_namespace, accepted_event_id)
               REFERENCES command_control_receipts(deployment_namespace, accepted_event_id)
        )""",
        """CREATE TABLE command_runtime_cleanup (
           deployment_namespace TEXT NOT NULL, accepted_event_id UUID NOT NULL,
           session_id UUID NOT NULL, scope_key TEXT NOT NULL,
           terminal_event_id UUID NOT NULL,
           status TEXT NOT NULL DEFAULT 'pending' CHECK(status IN ('pending','done')),
           created_at TIMESTAMPTZ NOT NULL DEFAULT clock_timestamp(),
           PRIMARY KEY(deployment_namespace, accepted_event_id),
           FOREIGN KEY(deployment_namespace, accepted_event_id)
               REFERENCES command_control_receipts(deployment_namespace, accepted_event_id)
        )""",
        """ALTER TABLE session_command_pending ADD COLUMN cancelled_by_control_id UUID,
           ADD CONSTRAINT command_cancelled_by_control_fk
               FOREIGN KEY(deployment_namespace, cancelled_by_control_id)
               REFERENCES command_control_receipts(deployment_namespace, accepted_event_id)""",
    ),
)
