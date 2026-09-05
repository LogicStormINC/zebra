"""v43: explicit historical retirement evidence, never an execution receipt."""

from agent_storage.postgres.migration_types import Migration

COMMAND_CUTOVER_MIGRATION = Migration(
    version=43, name="historical_command_retirement",
    statements=(
        """CREATE TABLE command_retirement_operations (
           deployment_namespace TEXT NOT NULL, operation_key TEXT NOT NULL,
           scope_key TEXT NOT NULL, tenant_id TEXT NOT NULL, workspace_id TEXT NOT NULL,
           task_id UUID NOT NULL, session_id UUID NOT NULL,
           expected_revision BIGINT NOT NULL, closure_event_id UUID NOT NULL,
           operator_id TEXT NOT NULL, reason TEXT NOT NULL,
           high_session_id UUID NOT NULL, high_sequence BIGINT NOT NULL,
           created_at TIMESTAMPTZ NOT NULL DEFAULT clock_timestamp(),
           PRIMARY KEY(deployment_namespace, operation_key),
           FOREIGN KEY(deployment_namespace, closure_event_id)
               REFERENCES session_events(deployment_namespace, event_id)
        )""",
        """CREATE TABLE command_retirements (
           deployment_namespace TEXT NOT NULL, accepted_event_id UUID NOT NULL,
           operation_key TEXT NOT NULL, scope_key TEXT NOT NULL,
           session_id UUID NOT NULL, command_id UUID NOT NULL, accepted_sequence BIGINT NOT NULL,
           PRIMARY KEY(deployment_namespace, accepted_event_id),
           FOREIGN KEY(deployment_namespace, operation_key)
               REFERENCES command_retirement_operations(deployment_namespace, operation_key),
           FOREIGN KEY(deployment_namespace, accepted_event_id)
               REFERENCES session_events(deployment_namespace, event_id)
        )""",
    ),
)
