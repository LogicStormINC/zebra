"""v73: derived Session index coverage and captured resumable preparation target."""

from agent_storage.postgres.migration_types import Migration

SESSION_RECOVERY_MIGRATION = Migration(
    version=73,
    name="session_recovery_frontiers",
    statements=(
        """CREATE INDEX session_events_recovery_page
            ON session_events(deployment_namespace,session_id,sequence)
            INCLUDE(event_bytes_bound)""",
        """CREATE TABLE session_recovery_frontiers (
            deployment_namespace TEXT NOT NULL, session_id UUID NOT NULL,
            index_sequence BIGINT NOT NULL DEFAULT -1 CHECK(index_sequence >= -1),
            highwater BIGINT NOT NULL CHECK(highwater >= index_sequence),
            PRIMARY KEY(deployment_namespace,session_id),
            FOREIGN KEY(deployment_namespace,session_id)
                REFERENCES session_streams(deployment_namespace,session_id) ON DELETE CASCADE
        )""",
    ),
)
