"""Migration v117: control-plane safety overrides for stuck executions.

The safety net is deliberately OUTSIDE the event store: sessions whose event
sequence is already corrupted cannot accept new events (including terminal
ones), so dead-letter/watchdog terminalization needs a control-plane channel
that readers (task headers/streams) treat as authoritative.
"""

from agent_storage.postgres.migration_types import Migration

SAFETY_OVERRIDE_MIGRATION = Migration(
    version=117,
    name="agent_safety_overrides",
    statements=(
        """
        CREATE TABLE agent_safety_overrides (
            deployment_namespace TEXT NOT NULL,
            session_id UUID NOT NULL,
            kind TEXT NOT NULL CHECK (kind IN (
                'failure_count', 'dead_letter', 'watchdog', 'zombie_repair'
            )),
            reason TEXT NOT NULL,
            diagnostics TEXT NOT NULL DEFAULT '',
            attempts INT NOT NULL DEFAULT 0 CHECK (attempts >= 0),
            shadow BOOLEAN NOT NULL DEFAULT FALSE,
            created_at TIMESTAMPTZ NOT NULL,
            updated_at TIMESTAMPTZ NOT NULL,
            PRIMARY KEY (deployment_namespace, session_id)
        )
        """,
        """
        CREATE INDEX agent_safety_overrides_terminal_idx
            ON agent_safety_overrides (deployment_namespace)
            WHERE kind IN ('dead_letter', 'watchdog', 'zombie_repair')
        """,
    ),
)
