"""Append-only manifest releases independent of connector authority revisions."""

from agent_storage.postgres.migration_types import Migration

HOST_MANIFEST_PUBLICATION_MIGRATION = Migration(
    version=122,
    name="host_manifest_publications",
    statements=(
        """
        CREATE TABLE host_manifest_publications (
            deployment_namespace TEXT NOT NULL,
            host_app_id TEXT NOT NULL,
            connector_id TEXT NOT NULL,
            profile_revision INTEGER NOT NULL CHECK (profile_revision >= 1),
            release_id BIGINT GENERATED ALWAYS AS IDENTITY,
            manifest_digest TEXT NOT NULL CHECK (manifest_digest ~ '^[0-9a-f]{64}$'),
            manifest_json JSONB NOT NULL CHECK (jsonb_typeof(manifest_json) = 'object'),
            published_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            PRIMARY KEY (deployment_namespace, host_app_id, connector_id,
                         profile_revision, release_id)
        )
        """,
        "CREATE INDEX host_manifest_publications_digest ON host_manifest_publications "
        "(deployment_namespace, manifest_digest)",
    ),
)
