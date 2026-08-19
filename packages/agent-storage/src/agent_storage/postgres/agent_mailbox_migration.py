"""PostgreSQL v28: durable agent team mailboxes."""

from agent_storage.postgres.migration_types import Migration

AGENT_MAILBOX_MIGRATION = Migration(
    version=28,
    name="agent_mailbox",
    statements=(
        """
        CREATE TABLE agent_mailbox_messages (
            deployment_namespace TEXT NOT NULL,
            message_id TEXT NOT NULL,
            team_id TEXT NOT NULL,
            sender TEXT NOT NULL,
            recipient TEXT NOT NULL,
            kind TEXT NOT NULL CHECK (kind IN (
                'task_assignment', 'direct_message', 'final_answer'
            )),
            subject TEXT NOT NULL,
            body TEXT NOT NULL,
            dedup_key TEXT NOT NULL,
            sent_at TIMESTAMPTZ NOT NULL,
            delivered_at TIMESTAMPTZ,
            PRIMARY KEY (deployment_namespace, message_id),
            UNIQUE (deployment_namespace, team_id, dedup_key)
        )
        """,
        """
        CREATE INDEX agent_mailbox_recipient
        ON agent_mailbox_messages (
            deployment_namespace, team_id, recipient, sent_at
        )
        """,
    ),
)
