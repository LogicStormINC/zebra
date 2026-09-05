"""v44: canonical command kinds for independently indexed pending lanes."""
from agent_storage.postgres.migration_types import Migration

COMMAND_PICKUP_MIGRATION = Migration(
    version=44, name="command_pending_pickup_lanes",
    statements=(
        "ALTER TABLE session_command_pending ADD COLUMN command_kind TEXT",
        """UPDATE session_command_pending AS pending SET command_kind=event.payload->>'kind'
           FROM session_events AS event
           WHERE event.deployment_namespace=pending.deployment_namespace
           AND event.event_id=pending.accepted_event_id
           AND event.event_type='session_command_accepted'""",
        """ALTER TABLE session_command_pending ALTER COLUMN command_kind SET NOT NULL,
           ADD CONSTRAINT command_pending_kind CHECK
           (command_kind IN ('run','resume','message','cancel','stop','suspend'))""",
        """CREATE INDEX command_pending_execution_pickup ON session_command_pending
           (deployment_namespace, created_at, accepted_event_id)
           WHERE status='pending' AND command_kind IN ('run','resume','message')""",
        """CREATE INDEX command_pending_control_pickup ON session_command_pending
           (deployment_namespace, created_at, accepted_event_id)
           WHERE status='pending' AND command_kind IN ('cancel','stop','suspend')""",
    ),
)
