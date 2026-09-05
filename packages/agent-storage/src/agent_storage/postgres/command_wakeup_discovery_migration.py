"""PostgreSQL v36: bounded explicit command backfill progress."""

from agent_storage.postgres.migration_types import Migration

COMMAND_DISCOVERY_MIGRATION = Migration(
    version=36,
    name="command_wakeup_backfill_progress",
    statements=(
        """ALTER TABLE command_wakeup_rollouts
           ADD COLUMN backfill_state TEXT NOT NULL DEFAULT 'not_started'
               CHECK (backfill_state IN ('not_started', 'running', 'complete')),
           ADD COLUMN high_session_id UUID,
           ADD COLUMN high_sequence BIGINT,
           ADD COLUMN cursor_session_id UUID,
           ADD COLUMN cursor_sequence BIGINT,
           ADD CONSTRAINT command_backfill_high_pair
               CHECK ((high_session_id IS NULL) = (high_sequence IS NULL)),
           ADD CONSTRAINT command_backfill_cursor_pair
               CHECK ((cursor_session_id IS NULL) = (cursor_sequence IS NULL))""",
        """CREATE INDEX session_events_command_backfill
           ON session_events (deployment_namespace, session_id, sequence)
           WHERE event_type = 'session_command_accepted'""",
    ),
)
