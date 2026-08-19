"""PostgreSQL durable mailbox store (ORCH-MAILBOX-PG-01).

Sends are deduplicated by content key; receives replay by cursor. The
permission policy is enforced by the caller (the domain contract); this
store owns durability, dedup and replay only.
"""

from __future__ import annotations

from typing import Any, Literal

from agent_core.domain.agent_mailbox import AgentMessage

from agent_storage.postgres.database import PostgresDatabase

_COLUMNS = (
    "message_id, team_id, sender, recipient, kind, subject, body, "
    "dedup_key, sent_at, delivered_at"
)


class PostgresAgentMailbox:
    """Durable, deduplicated mailbox over the v28 projection."""

    def __init__(self, dsn: str, *, deployment_namespace: str) -> None:
        self._database = PostgresDatabase(dsn, deployment_namespace=deployment_namespace)

    @property
    def deployment_namespace(self) -> str:
        return self._database.deployment_namespace

    def send(self, message: AgentMessage) -> Literal["delivered", "replayed"]:
        namespace = self.deployment_namespace
        with self._database.connect() as connection:
            inserted = connection.execute(
                """
                INSERT INTO agent_mailbox_messages (
                    deployment_namespace, message_id, team_id, sender, recipient,
                    kind, subject, body, dedup_key, sent_at
                ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                ON CONFLICT (deployment_namespace, team_id, dedup_key)
                DO NOTHING
                RETURNING message_id
                """,
                (
                    namespace,
                    message.message_id,
                    message.team_id,
                    message.sender,
                    message.recipient,
                    message.kind.value,
                    message.subject,
                    message.body,
                    message.dedup_key,
                    message.sent_at,
                ),
            ).fetchone()
        return "delivered" if inserted is not None else "replayed"

    def receive(
        self,
        team_id: str,
        recipient: str,
        *,
        since_sent_at: Any = None,
        limit: int = 50,
    ) -> tuple[AgentMessage, ...]:
        """Replay messages for one recipient from a durable cursor."""

        namespace = self.deployment_namespace
        with self._database.connect() as connection:
            if since_sent_at is None:
                rows = connection.execute(
                    f"""
                    SELECT {_COLUMNS} FROM agent_mailbox_messages
                    WHERE deployment_namespace = %s AND team_id = %s
                        AND recipient = %s
                    ORDER BY sent_at
                    LIMIT %s
                    """,
                    (namespace, team_id, recipient, limit),
                ).fetchall()
            else:
                rows = connection.execute(
                    f"""
                    SELECT {_COLUMNS} FROM agent_mailbox_messages
                    WHERE deployment_namespace = %s AND team_id = %s
                        AND recipient = %s AND sent_at > %s
                    ORDER BY sent_at
                    LIMIT %s
                    """,
                    (namespace, team_id, recipient, since_sent_at, limit),
                ).fetchall()
        return tuple(_message_from_row(row) for row in rows)


def _message_from_row(row: Any) -> AgentMessage:
    from agent_core.domain.agent_mailbox import MessageKind

    return AgentMessage(
        message_id=row["message_id"],
        team_id=row["team_id"],
        sender=row["sender"],
        recipient=row["recipient"],
        kind=MessageKind(row["kind"]),
        subject=row["subject"],
        body=row["body"],
        sent_at=row["sent_at"],
    )
