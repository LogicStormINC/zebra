"""v77: exact command/control prefix and immutable cancellation receipt Workspace."""

from agent_storage.postgres.migration_types import Migration

COMMAND_READ_STATE_MIGRATION = Migration(
    version=77,
    name="command_read_state",
    statements=(
        """CREATE TABLE session_command_read_heads (
            deployment_namespace TEXT NOT NULL, session_id UUID NOT NULL,
            through_sequence BIGINT NOT NULL DEFAULT -1 CHECK(through_sequence>=-1),
            highwater BIGINT NOT NULL DEFAULT -1 CHECK(highwater>=through_sequence),
            snapshot_json TEXT NOT NULL CHECK(octet_length(snapshot_json)<=1048576),
            PRIMARY KEY(deployment_namespace,session_id),
            FOREIGN KEY(deployment_namespace,session_id)
                REFERENCES session_streams(deployment_namespace,session_id) ON DELETE CASCADE
        )""",
        "ALTER TABLE direct_control_operations ADD COLUMN workspace_snapshot_json TEXT "
        "CHECK(octet_length(workspace_snapshot_json)<=1048576)",
        "CREATE INDEX direct_control_workspace_backfill ON direct_control_operations "
        "(deployment_namespace,terminal_event_id) WHERE workspace_snapshot_json IS NULL",
    ),
)
