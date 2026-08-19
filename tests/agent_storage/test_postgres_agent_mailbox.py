"""Real-PostgreSQL mailbox store tests (v28, ORCH-MAILBOX-PG-01)."""

from __future__ import annotations

import os
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from agent_core.domain.agent_mailbox import AgentMessage, MessageKind
from agent_storage import (
    apply_postgres_migrations,
    bootstrap_control_plane_epoch,
)
from agent_storage.postgres.agent_mailbox import PostgresAgentMailbox

NOW = datetime(2026, 8, 19, 12, 0, tzinfo=UTC)


@pytest.fixture(scope="session")
def postgres_dsn() -> str:
    dsn = os.environ.get("ZEBRA_TEST_POSTGRES_DSN")
    if not dsn:
        pytest.skip("set ZEBRA_TEST_POSTGRES_DSN to run real PostgreSQL tests")
    apply_postgres_migrations(dsn)
    return dsn


@pytest.fixture
def namespace(postgres_dsn: str) -> str:
    deployment_namespace = f"mailbox-{uuid4()}"
    bootstrap_control_plane_epoch(postgres_dsn, deployment_namespace=deployment_namespace)
    return deployment_namespace


def _message(
    *,
    subject: str = "task-a",
    kind: MessageKind = MessageKind.TASK_ASSIGNMENT,
    sent_at: datetime = NOW,
) -> AgentMessage:
    return AgentMessage(
        message_id=f"msg-{uuid4()}",
        team_id="team-1",
        sender="lead",
        recipient="mate-1",
        kind=kind,
        subject=subject,
        sent_at=sent_at,
    )


def test_send_deliver_and_dedup(namespace: str, postgres_dsn: str) -> None:
    mailbox = PostgresAgentMailbox(postgres_dsn, deployment_namespace=namespace)
    first = _message()
    assert mailbox.send(first) == "delivered"
    duplicate = first.model_copy(update={"message_id": f"msg-{uuid4()}"})
    assert mailbox.send(duplicate) == "replayed"
    received = mailbox.receive("team-1", "mate-1")
    assert len(received) == 1
    assert received[0].subject == "task-a"


def test_replay_from_cursor_without_duplicates(
    namespace: str, postgres_dsn: str
) -> None:
    mailbox = PostgresAgentMailbox(postgres_dsn, deployment_namespace=namespace)
    early = _message(subject="early", sent_at=NOW)
    late = _message(subject="late", sent_at=NOW + timedelta(seconds=30))
    assert mailbox.send(early) == "delivered"
    assert mailbox.send(late) == "delivered"
    full = mailbox.receive("team-1", "mate-1")
    assert [message.subject for message in full] == ["early", "late"]
    replayed = mailbox.receive(
        "team-1", "mate-1", since_sent_at=early.sent_at
    )
    assert [message.subject for message in replayed] == ["late"]


def test_recipients_are_isolated(namespace: str, postgres_dsn: str) -> None:
    mailbox = PostgresAgentMailbox(postgres_dsn, deployment_namespace=namespace)
    mailbox.send(_message(subject="for-mate-1"))
    assert mailbox.receive("team-1", "mate-2") == ()
