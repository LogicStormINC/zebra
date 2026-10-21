"""Additive v109 connector management receipts and audit; native rows stay intact."""

from agent_storage.postgres.migration_types import Migration

HOST_CONNECTOR_MANAGEMENT_MIGRATION = Migration(
    version=109,
    name="host_connector_management",
    statements=(
        """
        CREATE TABLE host_connector_management_receipts (
            deployment_namespace TEXT NOT NULL,
            host_app_id TEXT NOT NULL,
            namespace_id TEXT NOT NULL,
            operation_id UUID NOT NULL,
            payload_digest TEXT NOT NULL CHECK (payload_digest ~ '^[0-9a-f]{64}$'),
            snapshot JSONB NOT NULL,
            revision BIGINT NOT NULL CHECK (revision BETWEEN 1 AND 9007199254740991),
            observed_at TIMESTAMPTZ NOT NULL DEFAULT clock_timestamp(),
            PRIMARY KEY (deployment_namespace, host_app_id, namespace_id, operation_id)
        )
        """,
        """
        CREATE TABLE host_connector_management_audit (
            audit_id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
            deployment_namespace TEXT NOT NULL,
            host_app_id TEXT NOT NULL,
            namespace_id TEXT NOT NULL,
            trust_revision BIGINT NOT NULL,
            fingerprint TEXT NOT NULL,
            binding_revision BIGINT NOT NULL,
            operation_id UUID NOT NULL,
            active BOOLEAN NOT NULL,
            observed_at TIMESTAMPTZ NOT NULL DEFAULT clock_timestamp()
        )
        """,
    ),
)
