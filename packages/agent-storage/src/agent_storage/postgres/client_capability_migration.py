"""Migration v31: published frontend capability profiles and bindings."""

from agent_storage.postgres.migration_types import Migration

CLIENT_CAPABILITY_MIGRATION = Migration(
    version=31,
    name="client_capabilities",
    statements=(
        """
        CREATE TABLE frontend_capability_profiles (
            deployment_namespace TEXT NOT NULL,
            frontend_app_id TEXT NOT NULL,
            revision INTEGER NOT NULL CHECK (revision >= 1),
            profile_digest TEXT NOT NULL
                CHECK (profile_digest ~ '^[0-9a-f]{64}$'),
            lifecycle TEXT NOT NULL DEFAULT 'published'
                CHECK (lifecycle IN ('published', 'deprecated', 'revoked')),
            profile_json JSONB NOT NULL,
            published_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            PRIMARY KEY (deployment_namespace, frontend_app_id, revision),
            UNIQUE (deployment_namespace, frontend_app_id, profile_digest)
        )
        """,
        """
        CREATE TABLE frontend_capability_bindings (
            deployment_namespace TEXT NOT NULL,
            binding_id UUID NOT NULL,
            host_app_id TEXT NOT NULL,
            namespace_id TEXT NOT NULL,
            frontend_app_id TEXT NOT NULL,
            revision INTEGER NOT NULL CHECK (revision >= 1),
            profile_digest TEXT NOT NULL
                CHECK (profile_digest ~ '^[0-9a-f]{64}$'),
            binding_revision INTEGER NOT NULL CHECK (binding_revision >= 1),
            bound_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            PRIMARY KEY (deployment_namespace, binding_id)
        )
        """,
    ),
)
