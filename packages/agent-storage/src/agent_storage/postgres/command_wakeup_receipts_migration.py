"""v39: exact worker-boundary Event attribution, not a sequence completion watermark."""

from agent_storage.postgres.migration_types import Migration

COMMAND_RECEIPTS_MIGRATION = Migration(
    version=39,
    name="command_execution_event_receipts",
    statements=(
        """ALTER TABLE command_handoff_receipts
           ADD COLUMN execution_floor_sequence BIGINT CHECK (execution_floor_sequence >= 0),
           ADD COLUMN started_event_id UUID,
           ADD COLUMN handled_event_id UUID,
           ADD COLUMN turn_id TEXT,
           ADD CONSTRAINT command_started_event_fk
               FOREIGN KEY (deployment_namespace, started_event_id)
               REFERENCES session_events (deployment_namespace, event_id),
           ADD CONSTRAINT command_handled_event_fk
               FOREIGN KEY (deployment_namespace, handled_event_id)
               REFERENCES session_events (deployment_namespace, event_id),
           ADD CONSTRAINT command_handled_requires_start
               CHECK (handled_event_id IS NULL OR started_event_id IS NOT NULL)""",
        """CREATE UNIQUE INDEX command_receipt_exact_fence ON command_handoff_receipts (
               deployment_namespace, session_id, control_plane_epoch,
               fencing_token, owner_instance_id
           ) WHERE status = 'accepted'""",
    ),
)
