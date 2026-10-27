"""Additive v108 management approvals, CAS revisions and operation evidence."""

from agent_storage.postgres.migration_types import Migration

HOST_MANAGEMENT_MIGRATION = Migration(
    version=108,
    name="host_registry_management",
    statements=(
        """
        ALTER TABLE host_authority_registries ADD COLUMN revision BIGINT NOT NULL
            DEFAULT 1 CHECK (revision > 0)
        """,
        """
        CREATE TABLE host_management_approvals (
            deployment_namespace TEXT NOT NULL,
            host_app_id TEXT NOT NULL,
            namespace_id TEXT NOT NULL,
            deployment_id TEXT NOT NULL,
            audience TEXT NOT NULL,
            product_id TEXT NOT NULL,
            environment TEXT NOT NULL,
            revision BIGINT NOT NULL CHECK (revision BETWEEN 1 AND 9007199254740991),
            fingerprint TEXT NOT NULL CHECK (fingerprint ~ '^[0-9a-f]{64}$'),
            expires_at TIMESTAMPTZ NOT NULL,
            updated_at TIMESTAMPTZ NOT NULL DEFAULT clock_timestamp(),
            PRIMARY KEY (deployment_namespace, host_app_id, namespace_id)
        )
        """,
        """
        CREATE TABLE host_management_receipts (
            deployment_namespace TEXT NOT NULL,
            host_app_id TEXT NOT NULL,
            namespace_id TEXT NOT NULL,
            operation_id UUID NOT NULL,
            payload_digest TEXT NOT NULL CHECK (payload_digest ~ '^[0-9a-f]{64}$'),
            registry JSONB NOT NULL,
            revision BIGINT NOT NULL CHECK (revision BETWEEN 1 AND 9007199254740991),
            observed_at TIMESTAMPTZ NOT NULL DEFAULT clock_timestamp(),
            PRIMARY KEY (deployment_namespace, host_app_id, namespace_id, operation_id)
        )
        """,
        """
        CREATE TABLE host_management_audit (
            audit_id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
            deployment_namespace TEXT NOT NULL,
            host_app_id TEXT NOT NULL,
            namespace_id TEXT NOT NULL,
            action TEXT NOT NULL CHECK (action IN ('approve', 'apply')),
            trust_revision BIGINT NOT NULL,
            fingerprint TEXT NOT NULL CHECK (fingerprint ~ '^[0-9a-f]{64}$'),
            registry_revision BIGINT,
            operation_id UUID,
            observed_at TIMESTAMPTZ NOT NULL DEFAULT clock_timestamp()
        )
        """,
    ),
)
