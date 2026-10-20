"""PostgreSQL v107: Host-scoped manifest revisions; legacy freezes stay intact."""

from agent_storage.postgres.migration_types import Migration

HOST_MANIFEST_REVISION_MIGRATION = Migration(
    version=107,
    name="host_manifest_revisions",
    statements=(
        """
        CREATE TABLE host_manifest_revisions (
            deployment_namespace TEXT NOT NULL,
            host_app_id TEXT NOT NULL CHECK (length(btrim(host_app_id)) > 0),
            connector_id TEXT NOT NULL CHECK (length(btrim(connector_id)) > 0),
            profile_revision INTEGER NOT NULL CHECK (profile_revision >= 1),
            manifest_digest TEXT NOT NULL CHECK (manifest_digest ~ '^[0-9a-f]{64}$'),
            manifest_json JSONB NOT NULL CHECK (jsonb_typeof(manifest_json) = 'object'),
            fetched_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            PRIMARY KEY (deployment_namespace, host_app_id, connector_id, profile_revision)
        )
        """,
        "CREATE INDEX host_manifest_revisions_digest ON host_manifest_revisions "
        "(deployment_namespace, manifest_digest)",
    ),
)
