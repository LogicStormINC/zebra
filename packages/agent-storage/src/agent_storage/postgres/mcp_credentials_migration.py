"""PostgreSQL v55: immutable, scoped encrypted MCP credential versions."""

from agent_storage.postgres.migration_types import Migration

MCP_CREDENTIALS_MIGRATION = Migration(
    version=55,
    name="encrypted_mcp_credential_versions",
    statements=(
        """
        CREATE TABLE mcp_credential_versions (
            key_digest TEXT NOT NULL CHECK (key_digest ~ '^[0-9a-f]{64}$'),
            scope_digest TEXT NOT NULL,
            deployment_namespace TEXT NOT NULL,
            authority_issuer TEXT NOT NULL,
            namespace_id TEXT NOT NULL,
            principal_id TEXT NOT NULL,
            workspace_id TEXT NOT NULL,
            kind TEXT NOT NULL DEFAULT 'mcp' CHECK (kind = 'mcp'),
            object_id TEXT NOT NULL,
            credential_ref TEXT NOT NULL,
            revision BIGINT NOT NULL CHECK (revision > 0),
            binding JSONB NOT NULL CHECK (jsonb_typeof(binding) = 'object'),
            key_handle TEXT NOT NULL CHECK (length(key_handle) BETWEEN 1 AND 512),
            key_version TEXT NOT NULL CHECK (length(key_version) BETWEEN 1 AND 512),
            nonce BYTEA NOT NULL CHECK (octet_length(nonce) = 12),
            ciphertext BYTEA NOT NULL CHECK (octet_length(ciphertext) BETWEEN 17 AND 16400),
            PRIMARY KEY (key_digest, revision),
            FOREIGN KEY (scope_digest, kind, object_id) REFERENCES extension_configurations
        )
        """,
    ),
)
