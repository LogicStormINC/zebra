"""PostgreSQL v106: explicit nullable Host manifest policy; old rows stay NULL."""

from agent_storage.postgres.migration_types import Migration

HOST_MANIFEST_POLICY_MIGRATION = Migration(
    version=106,
    name="host_manifest_binding_policy",
    statements=(
        "ALTER TABLE host_connector_profiles ADD COLUMN manifest_binding_policy TEXT "
        "CHECK (manifest_binding_policy IN ('declared', 'legacy'))",
    ),
)
