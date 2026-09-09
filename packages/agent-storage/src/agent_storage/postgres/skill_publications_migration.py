"""PostgreSQL v52: immutable package reservations, followed by verified readiness."""

from agent_storage.postgres.migration_types import Migration

SKILL_PUBLICATIONS_MIGRATION = Migration(
    version=52,
    name="skill_package_publications",
    statements=("""
        CREATE TABLE skill_package_versions (
            scope_digest TEXT NOT NULL CHECK (scope_digest ~ '^[0-9a-f]{64}$'),
            deployment_namespace TEXT NOT NULL,
            authority_issuer TEXT NOT NULL,
            namespace_id TEXT NOT NULL,
            principal_id TEXT NOT NULL,
            workspace_id TEXT NOT NULL,
            skill_id TEXT NOT NULL,
            version_id TEXT NOT NULL,
            name TEXT NOT NULL CHECK (length(name) BETWEEN 1 AND 64),
            version_label TEXT NOT NULL CHECK (length(version_label) BETWEEN 1 AND 64),
            payload JSONB NOT NULL CHECK (jsonb_typeof(payload) = 'object'),
            PRIMARY KEY (scope_digest, skill_id, version_id),
            UNIQUE (scope_digest, name, version_label)
        )
        """,),
)
