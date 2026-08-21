"""Migration v30: durable Host manifest freezes (ADR-017 admission freeze)."""

from agent_storage.postgres.migration_types import Migration

HOST_MANIFEST_FREEZE_MIGRATION = Migration(
    version=30,
    name="host_manifest_freezes",
    statements=(
        """
        CREATE TABLE host_manifest_freezes (
            deployment_namespace TEXT NOT NULL,
            manifest_digest TEXT NOT NULL
                CHECK (manifest_digest ~ '^[0-9a-f]{64}$'),
            connector_id TEXT NOT NULL
                CHECK (length(btrim(connector_id)) > 0),
            profile_revision INTEGER NOT NULL CHECK (profile_revision >= 1),
            manifest_json JSONB NOT NULL
                CHECK (jsonb_typeof(manifest_json) = 'object'),
            fetched_at TIMESTAMPTZ NOT NULL,
            PRIMARY KEY (deployment_namespace, manifest_digest),
            UNIQUE (deployment_namespace, connector_id, profile_revision)
        )
        """,
    ),
)
