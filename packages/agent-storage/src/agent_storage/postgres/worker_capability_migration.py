"""Process capabilities are not Session leases or an HTTP admission switch."""

from agent_storage.postgres.migration_types import Migration

WORKER_CAPABILITY_MIGRATION = Migration(
    version=82,
    name="worker_process_capability_leases",
    statements=(
        """CREATE TABLE worker_process_capabilities (
            deployment_namespace TEXT NOT NULL REFERENCES control_plane_epochs,
            process_id UUID NOT NULL,
            epoch UUID NOT NULL,
            database_name TEXT NOT NULL,
            schema_name TEXT NOT NULL,
            schema_oid OID NOT NULL,
            contract TEXT NOT NULL,
            configuration_digest TEXT NOT NULL
                CHECK (configuration_digest ~ '^[0-9a-f]{64}$'),
            sequence BIGINT NOT NULL CHECK (sequence >= 1),
            registered_at TIMESTAMPTZ NOT NULL,
            heartbeat_at TIMESTAMPTZ NOT NULL,
            expires_at TIMESTAMPTZ NOT NULL,
            revoked_at TIMESTAMPTZ,
            PRIMARY KEY (deployment_namespace, process_id),
            CHECK (expires_at > heartbeat_at),
            CHECK (heartbeat_at >= registered_at)
        )""",
        """CREATE INDEX worker_process_capability_lookup
           ON worker_process_capabilities
             (deployment_namespace, contract, configuration_digest, expires_at)
           WHERE revoked_at IS NULL""",
    ),
)
