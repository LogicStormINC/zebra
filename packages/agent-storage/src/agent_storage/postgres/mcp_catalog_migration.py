"""PostgreSQL v56: immutable scoped MCP tool catalog versions."""

from agent_storage.postgres.migration_types import Migration

MCP_CATALOG_MIGRATION = Migration(
    version=56,
    name="scoped_mcp_tool_catalog_versions",
    statements=(
        """
        CREATE TABLE mcp_catalog_versions (
            scope_digest TEXT NOT NULL,
            deployment_namespace TEXT NOT NULL,
            authority_issuer TEXT NOT NULL,
            namespace_id TEXT NOT NULL,
            principal_id TEXT NOT NULL,
            workspace_id TEXT NOT NULL,
            kind TEXT NOT NULL CHECK (kind = 'mcp'),
            object_id TEXT NOT NULL,
            revision BIGINT NOT NULL CHECK (revision > 0),
            digest TEXT NOT NULL CHECK (digest ~ '^[0-9a-f]{64}$'),
            publication_sequence BIGSERIAL NOT NULL,
            payload JSONB NOT NULL CHECK (jsonb_typeof(payload) = 'object'),
            PRIMARY KEY (scope_digest, kind, object_id, revision, digest),
            FOREIGN KEY (scope_digest, kind, object_id, revision)
                REFERENCES extension_configuration_revisions
        )
        """,
        """CREATE INDEX mcp_catalog_latest ON mcp_catalog_versions
           (scope_digest, kind, object_id, revision, publication_sequence DESC)""",
    ),
)
