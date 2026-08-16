"""PostgreSQL v23: durable tenant namespace on session projections."""

from agent_storage.postgres.migration_types import Migration

SESSION_TENANT_NAMESPACE_MIGRATION = Migration(
    version=23,
    name="session_tenant_namespace",
    statements=(
        """
        ALTER TABLE session_projections
        ADD COLUMN namespace_id TEXT CHECK (
            namespace_id IS NULL OR length(btrim(namespace_id)) BETWEEN 1 AND 255
        )
        """,
        """
        CREATE INDEX session_projections_tenant
        ON session_projections (deployment_namespace, namespace_id, updated_at DESC)
        WHERE namespace_id IS NOT NULL
        """,
    ),
)
