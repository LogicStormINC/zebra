"""PostgreSQL v54: immutable exact-scope per-turn extension inputs."""

from agent_storage.postgres.migration_types import Migration

EXTENSION_SNAPSHOTS_MIGRATION = Migration(
    version=54,
    name="turn_extension_snapshots",
    statements=(
        """
        CREATE TABLE turn_extension_snapshots (
            key_digest TEXT PRIMARY KEY CHECK (key_digest ~ '^[0-9a-f]{64}$'),
            deployment_namespace TEXT NOT NULL,
            authority_issuer TEXT NOT NULL,
            namespace_id TEXT NOT NULL,
            principal_id TEXT NOT NULL,
            workspace_id TEXT NOT NULL,
            session_id TEXT NOT NULL,
            turn_id TEXT NOT NULL,
            snapshot_digest TEXT NOT NULL CHECK (snapshot_digest ~ '^[0-9a-f]{64}$'),
            payload JSONB NOT NULL CHECK (jsonb_typeof(payload) = 'object')
        )
        """,
    ),
)
