"""v41: exact canonical MESSAGE input association survives receipt rebind."""

from agent_storage.postgres.migration_types import Migration

COMMAND_MESSAGE_MIGRATION = Migration(
    version=41, name="command_message_input_receipt",
    statements=(
        """ALTER TABLE command_handoff_receipts ADD COLUMN input_event_id UUID,
           ADD CONSTRAINT command_message_input_fk
               FOREIGN KEY(deployment_namespace, input_event_id)
               REFERENCES session_events(deployment_namespace, event_id)""",
    ),
)
