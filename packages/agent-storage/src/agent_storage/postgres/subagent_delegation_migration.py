"""PostgreSQL v26: durable parent-child delegation links."""

from agent_storage.postgres.migration_types import Migration

SUBAGENT_DELEGATION_MIGRATION = Migration(
    version=26,
    name="subagent_delegation_links",
    statements=(
        """
        CREATE TABLE subagent_delegation_links (
            deployment_namespace TEXT NOT NULL,
            delegation_id TEXT NOT NULL,
            idempotency_key TEXT NOT NULL,
            root_task_id UUID NOT NULL,
            parent_task_id UUID NOT NULL,
            parent_binding_digest TEXT NOT NULL,
            child_task_id UUID NOT NULL,
            child_binding_digest TEXT,
            plan_revision BIGINT,
            node_key TEXT,
            created_at TIMESTAMPTZ NOT NULL DEFAULT transaction_timestamp(),
            terminal_at TIMESTAMPTZ,
            PRIMARY KEY (deployment_namespace, delegation_id),
            UNIQUE (deployment_namespace, parent_task_id, idempotency_key),
            UNIQUE (deployment_namespace, child_task_id)
        )
        """,
        """
        CREATE INDEX subagent_delegation_children
        ON subagent_delegation_links (deployment_namespace, parent_task_id, created_at)
        """,
    ),
)
