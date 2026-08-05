"""PostgreSQL v16 schema for namespace-scoped migration cutovers."""

from agent_storage.postgres.migration_types import Migration

MIGRATION_RECOVERY_MIGRATION = Migration(
    version=16,
    name="migration_recovery_cutover_guard",
    statements=(
        """
        CREATE TABLE control_plane_cutovers (
            deployment_namespace TEXT NOT NULL
                CHECK (length(btrim(deployment_namespace)) > 0),
            cutover_id UUID NOT NULL,
            state TEXT NOT NULL CHECK (state IN ('prepared', 'verified', 'active')),
            manifest_sha256 TEXT NOT NULL CHECK (length(manifest_sha256) = 64),
            created_at TIMESTAMPTZ NOT NULL DEFAULT transaction_timestamp(),
            verified_at TIMESTAMPTZ,
            activated_at TIMESTAMPTZ,
            PRIMARY KEY (deployment_namespace, cutover_id),
            CHECK (state <> 'verified' OR verified_at IS NOT NULL),
            CHECK (state <> 'active' OR (verified_at IS NOT NULL AND activated_at IS NOT NULL))
        )
        """,
        """
        CREATE UNIQUE INDEX control_plane_cutovers_one_active
        ON control_plane_cutovers (deployment_namespace)
        WHERE state = 'active'
        """,
    ),
)
