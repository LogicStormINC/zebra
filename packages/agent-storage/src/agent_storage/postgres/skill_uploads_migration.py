"""PostgreSQL v53: exact-scope upload retry keys; only key digests are retained."""

from agent_storage.postgres.migration_types import Migration

SKILL_UPLOADS_MIGRATION = Migration(
    version=53,
    name="skill_package_upload_keys",
    statements=("""
        CREATE TABLE skill_package_upload_keys (
            scope_digest TEXT NOT NULL CHECK (scope_digest ~ '^[0-9a-f]{64}$'),
            deployment_namespace TEXT NOT NULL,
            authority_issuer TEXT NOT NULL,
            namespace_id TEXT NOT NULL,
            principal_id TEXT NOT NULL,
            workspace_id TEXT NOT NULL,
            key_digest TEXT NOT NULL CHECK (key_digest ~ '^[0-9a-f]{64}$'),
            skill_id TEXT NOT NULL,
            version_id TEXT NOT NULL,
            archive_sha256 TEXT NOT NULL CHECK (archive_sha256 ~ '^[0-9a-f]{64}$'),
            archive_size BIGINT NOT NULL CHECK (archive_size BETWEEN 0 AND 10485760),
            PRIMARY KEY (scope_digest, key_digest)
        )
        """,),
)
