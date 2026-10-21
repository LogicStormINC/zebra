"""Additive v110 immutable native Bundle Definition sidecars; legacy rows unchanged."""

from agent_storage.postgres.migration_types import Migration

BUNDLE_DEFINITION_MIGRATION = Migration(
    version=110,
    name="agent_definition_bundle_versions",
    statements=(
        """
        CREATE TABLE agent_definition_bundle_versions (
            authority_issuer TEXT NOT NULL,
            namespace_id TEXT NOT NULL,
            definition_id UUID NOT NULL,
            version_id UUID NOT NULL,
            snapshot JSONB NOT NULL CHECK (jsonb_typeof(snapshot) = 'object'),
            PRIMARY KEY (authority_issuer, namespace_id, definition_id, version_id),
            FOREIGN KEY (authority_issuer, namespace_id, definition_id, version_id)
                REFERENCES agent_definition_versions (
                    authority_issuer, namespace_id, definition_id, version_id
                )
        )
    """,
    ),
)
