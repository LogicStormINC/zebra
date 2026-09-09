"""PostgreSQL v51: scoped extension configuration and immutable revision payloads."""

from agent_storage.postgres.migration_types import Migration

EXTENSIONS_MIGRATION = Migration(
    version=51,
    name="scoped_extension_configuration",
    statements=(
        """
        CREATE TABLE extension_configurations (
            scope_digest TEXT NOT NULL CHECK (scope_digest ~ '^[0-9a-f]{64}$'),
            deployment_namespace TEXT NOT NULL,
            authority_issuer TEXT NOT NULL,
            namespace_id TEXT NOT NULL,
            principal_id TEXT NOT NULL,
            workspace_id TEXT NOT NULL,
            kind TEXT NOT NULL CHECK (kind IN ('skill', 'mcp')),
            object_id TEXT COLLATE "C" NOT NULL,
            revision BIGINT NOT NULL CHECK (revision > 0),
            PRIMARY KEY (scope_digest, kind, object_id)
        )
        """,
        """
        CREATE TABLE extension_configuration_revisions (
            scope_digest TEXT NOT NULL CHECK (scope_digest ~ '^[0-9a-f]{64}$'),
            deployment_namespace TEXT NOT NULL,
            authority_issuer TEXT NOT NULL,
            namespace_id TEXT NOT NULL,
            principal_id TEXT NOT NULL,
            workspace_id TEXT NOT NULL,
            kind TEXT NOT NULL CHECK (kind IN ('skill', 'mcp')),
            object_id TEXT COLLATE "C" NOT NULL,
            revision BIGINT NOT NULL CHECK (revision > 0),
            payload JSONB NOT NULL CHECK (jsonb_typeof(payload) = 'object'),
            PRIMARY KEY (scope_digest, kind, object_id, revision),
            FOREIGN KEY (scope_digest, kind, object_id)
                REFERENCES extension_configurations
        )
        """,
    ),
)
