"""v48: direct cancellation anchors sharing the existing exact cleanup queue."""

from agent_storage.postgres.migration_types import Migration

DIRECT_CONTROL_MIGRATION = Migration(
    version=48,
    name="direct_control_cleanup_anchors",
    statements=(
        """CREATE TABLE direct_control_operations (
       deployment_namespace TEXT NOT NULL, operation_id UUID NOT NULL,
       session_id UUID NOT NULL, authority_issuer TEXT NOT NULL, tenant_id TEXT NOT NULL,
       workspace_id TEXT, scope_key TEXT NOT NULL, request_key TEXT,
       terminal_event_id UUID NOT NULL,
       revoked_epoch UUID, revoked_token BIGINT, revoked_owner TEXT,
       created_at TIMESTAMPTZ NOT NULL DEFAULT clock_timestamp(),
       PRIMARY KEY(deployment_namespace,operation_id), UNIQUE(deployment_namespace,request_key),
       FOREIGN KEY(deployment_namespace,session_id)
         REFERENCES session_streams(deployment_namespace,session_id),
       FOREIGN KEY(deployment_namespace,terminal_event_id)
         REFERENCES session_events(deployment_namespace,event_id))""",
        """ALTER TABLE command_runtime_cleanup ADD COLUMN cleanup_id UUID,
       ADD COLUMN direct_operation_id UUID,
       ADD CONSTRAINT cleanup_direct_operation_fk
       FOREIGN KEY(deployment_namespace,direct_operation_id)
         REFERENCES direct_control_operations(deployment_namespace,operation_id)""",
        """UPDATE command_runtime_cleanup SET cleanup_id=accepted_event_id""",
        """ALTER TABLE command_runtime_cleanup DROP CONSTRAINT command_runtime_cleanup_pkey,
       ALTER COLUMN accepted_event_id DROP NOT NULL,
       ALTER COLUMN cleanup_id SET NOT NULL, ALTER COLUMN cleanup_id SET DEFAULT gen_random_uuid(),
       ADD PRIMARY KEY(deployment_namespace,cleanup_id),
       ADD UNIQUE(deployment_namespace,accepted_event_id),
       ADD UNIQUE(deployment_namespace,direct_operation_id),
       ADD CONSTRAINT cleanup_exactly_one_anchor
         CHECK((accepted_event_id IS NOT NULL)::int+(direct_operation_id IS NOT NULL)::int=1)""",
        "DROP INDEX command_runtime_cleanup_due",
        "DROP INDEX command_runtime_cleanup_expired",
        """CREATE INDEX command_cleanup_due_identity ON command_runtime_cleanup
       (deployment_namespace,available_at,cleanup_id) WHERE status='pending'""",
        """CREATE INDEX command_cleanup_expired_identity ON command_runtime_cleanup
       (deployment_namespace,lease_expires_at,available_at,cleanup_id) WHERE status='cleaning'""",
    ),
)
