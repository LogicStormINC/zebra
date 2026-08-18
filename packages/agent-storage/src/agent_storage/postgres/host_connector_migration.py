"""PostgreSQL v24: outbound Host connector profiles and namespace bindings."""

from agent_storage.postgres.migration_types import Migration

HOST_CONNECTOR_MIGRATION = Migration(
    version=24,
    name="host_connector_registry",
    statements=(
        """
        CREATE TABLE host_connector_profiles (
            deployment_namespace TEXT NOT NULL,
            host_app_id TEXT NOT NULL,
            connector_id TEXT NOT NULL,
            profile_revision BIGINT NOT NULL CHECK (profile_revision >= 1),
            base_uri TEXT NOT NULL,
            manifest_path TEXT NOT NULL,
            invoke_path_template TEXT NOT NULL,
            reconcile_path_template TEXT,
            supported_protocol_versions JSONB NOT NULL,
            workload_identity_ref TEXT NOT NULL,
            credential_ref TEXT NOT NULL,
            network_policy_ref TEXT,
            status TEXT NOT NULL
                CHECK (status IN ('published', 'deprecated', 'revoked')),
            profile_digest TEXT NOT NULL,
            created_at TIMESTAMPTZ NOT NULL DEFAULT transaction_timestamp(),
            PRIMARY KEY (deployment_namespace, host_app_id, connector_id, profile_revision)
        )
        """,
        """
        CREATE TABLE host_connector_bindings (
            deployment_namespace TEXT NOT NULL,
            host_app_id TEXT NOT NULL,
            namespace_id TEXT NOT NULL,
            connector_id TEXT NOT NULL,
            profile_revision BIGINT NOT NULL CHECK (profile_revision >= 1),
            binding_revision BIGINT NOT NULL CHECK (binding_revision >= 1),
            active BOOLEAN NOT NULL DEFAULT TRUE,
            updated_at TIMESTAMPTZ NOT NULL DEFAULT transaction_timestamp(),
            PRIMARY KEY (deployment_namespace, host_app_id, namespace_id)
        )
        """,
        """
        CREATE INDEX host_connector_profiles_status
        ON host_connector_profiles (deployment_namespace, status, host_app_id)
        """,
        """
        CREATE INDEX host_connector_bindings_active
        ON host_connector_bindings (deployment_namespace, active, updated_at DESC)
        """,
    ),
)
