"""PostgreSQL v25: immutable Task binding snapshots for atomic admission."""

from agent_storage.postgres.migration_types import Migration

TASK_BINDING_MIGRATION = Migration(
    version=25,
    name="task_binding_snapshots",
    statements=(
        """
        CREATE TABLE task_binding_snapshots (
            deployment_namespace TEXT NOT NULL,
            task_id UUID NOT NULL,
            binding_revision BIGINT NOT NULL CHECK (binding_revision >= 1),
            binding_digest TEXT NOT NULL,
            definition_snapshot_digest TEXT NOT NULL,
            host_manifest_digest TEXT NOT NULL,
            connector_profile_digest TEXT NOT NULL,
            grant_digest TEXT NOT NULL,
            snapshot_json JSONB NOT NULL,
            effective_capabilities JSONB NOT NULL,
            bound_at TIMESTAMPTZ NOT NULL,
            PRIMARY KEY (deployment_namespace, task_id, binding_revision)
        )
        """,
        """
        CREATE INDEX task_binding_snapshots_latest
        ON task_binding_snapshots (deployment_namespace, task_id, binding_revision DESC)
        """,
    ),
)
