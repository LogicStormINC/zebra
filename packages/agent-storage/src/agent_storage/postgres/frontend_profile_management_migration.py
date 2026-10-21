"""Additive v112 scoped frontend ownership and immutable operation evidence."""

from agent_storage.postgres.migration_types import Migration

FRONTEND_PROFILE_MANAGEMENT_MIGRATION = Migration(
    version=112,
    name="frontend_profile_management",
    statements=(
        """CREATE TABLE frontend_profile_management (
        deployment_namespace TEXT NOT NULL, frontend_app_id TEXT NOT NULL,
        product_id TEXT NOT NULL, environment TEXT NOT NULL,
        host_app_id TEXT NOT NULL, namespace_id TEXT NOT NULL,
        revision BIGINT NOT NULL CHECK(revision>=0),
        PRIMARY KEY(deployment_namespace,frontend_app_id))""",
        """CREATE TABLE frontend_profile_management_receipts (
        deployment_namespace TEXT NOT NULL, frontend_app_id TEXT NOT NULL,
        operation_id UUID NOT NULL, payload_digest TEXT NOT NULL,
        trust_revision BIGINT NOT NULL, fingerprint TEXT NOT NULL,
        result JSONB NOT NULL, created_at TIMESTAMPTZ NOT NULL DEFAULT clock_timestamp(),
        PRIMARY KEY(deployment_namespace,frontend_app_id,operation_id))""",
    ),
)
