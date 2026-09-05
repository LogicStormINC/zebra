"""v46: exact cloud runtime identity, including unsettled create obligations."""

from agent_storage.postgres.migration_types import Migration

RUNTIME_INSTANCES_MIGRATION = Migration(
    version=46,
    name="runtime_instances",
    statements=(
        """CREATE TABLE runtime_instances (
          deployment_namespace TEXT NOT NULL, instance_id UUID NOT NULL,
          session_id UUID NOT NULL, tenant_id TEXT NOT NULL, workspace_id TEXT,
          authority_issuer TEXT NOT NULL,
          scope_key TEXT NOT NULL, control_plane_epoch UUID NOT NULL,
          fencing_token BIGINT NOT NULL CHECK(fencing_token>0), owner_instance_id TEXT NOT NULL,
          spec_digest TEXT NOT NULL, engine_identity TEXT NOT NULL,
          container_name TEXT NOT NULL, container_id TEXT,
          status TEXT NOT NULL DEFAULT 'provisioning'
            CHECK(status IN ('provisioning','created','removed')),
          created_at TIMESTAMPTZ NOT NULL DEFAULT clock_timestamp(), removed_at TIMESTAMPTZ,
          PRIMARY KEY(deployment_namespace, instance_id),
          UNIQUE(engine_identity, container_name),
          FOREIGN KEY(deployment_namespace, session_id)
            REFERENCES session_streams(deployment_namespace, session_id)
        )""",
        """CREATE INDEX runtime_instance_obligations ON runtime_instances
          (deployment_namespace, session_id, created_at, instance_id) WHERE status<>'removed'""",
    ),
)
