"""Additive product distribution facts; existing installation history is untouched."""

from agent_storage.postgres.migration_types import Migration

PLUGIN_DISTRIBUTION_MIGRATION = Migration(
    version=114,
    name="plugin_product_distribution",
    statements=(
        "CREATE TABLE plugin_managed_packages (deployment_namespace TEXT NOT NULL, "
        "package_digest TEXT NOT NULL, PRIMARY "
        "KEY(deployment_namespace,package_digest))",
        "CREATE TABLE plugin_product_distributions (deployment_namespace TEXT NOT "
        "NULL, package_digest TEXT NOT NULL, scope_digest TEXT NOT NULL, actor TEXT "
        "NOT NULL, revision BIGINT NOT NULL CHECK(revision>0), payload JSONB NOT NULL, "
        "PRIMARY KEY(deployment_namespace,package_digest,scope_digest))",
        "INSERT INTO plugin_managed_packages SELECT DISTINCT deployment_namespace,"
        "result->>'packageDigest' FROM runtime_publication_receipts "
        "WHERE result->>'contractVersion'='plugin-admission/1' "
        "AND result->>'packageDigest' ~ '^sha256:[0-9a-f]{64}$' ON CONFLICT DO NOTHING",
    ),
)
