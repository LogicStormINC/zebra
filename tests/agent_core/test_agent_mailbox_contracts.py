"""Mailbox contract tests: kinds, permissions, limits, dedup."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from agent_core.domain.agent_mailbox import (
    AgentMessage,
    FrequencyPolicy,
    MailboxPermissionError,
    MailboxPermissionPolicy,
    MessageKind,
    dedup_resolution,
)
from pydantic import ValidationError

NOW = datetime(2026, 8, 19, 12, 0, tzinfo=UTC)


def _message(
    *,
    sender: str = "lead",
    recipient: str = "mate-1",
    kind: MessageKind = MessageKind.DIRECT_MESSAGE,
    subject: str = "status",
    body: str = "",
    sent_at: datetime = NOW,
) -> AgentMessage:
    return AgentMessage(
        message_id=f"msg-{uuid4()}",
        team_id="team-1",
        sender=sender,
        recipient=recipient,
        kind=kind,
        subject=subject,
        body=body,
        sent_at=sent_at,
    )


def _policy() -> MailboxPermissionPolicy:
    return MailboxPermissionPolicy(
        team_id="team-1",
        lead="lead",
        members=frozenset({"lead", "mate-1", "mate-2"}),
    )


class TestPermissions:
    def test_lead_assigns_tasks_to_members(self) -> None:
        message = _message(kind=MessageKind.TASK_ASSIGNMENT, subject="task-a")
        assert _policy().authorize(message) is message

    def test_teammates_cannot_assign_tasks(self) -> None:
        with pytest.raises(MailboxPermissionError, match="only the lead"):
            _policy().authorize(
                _message(sender="mate-1", recipient="mate-2", kind=MessageKind.TASK_ASSIGNMENT)
            )

    def test_assignment_to_non_member_rejected(self) -> None:
        with pytest.raises(MailboxPermissionError, match="non-member"):
            _policy().authorize(
                _message(recipient="outsider", kind=MessageKind.TASK_ASSIGNMENT)
            )

    def test_final_answers_go_to_the_lead_only(self) -> None:
        message = _message(sender="mate-1", recipient="lead", kind=MessageKind.FINAL_ANSWER)
        assert _policy().authorize(message) is message
        with pytest.raises(MailboxPermissionError, match="lead only"):
            _policy().authorize(_message(kind=MessageKind.FINAL_ANSWER))
        with pytest.raises(MailboxPermissionError, match="lead does not send"):
            _policy().authorize(
                _message(sender="lead", recipient="lead", kind=MessageKind.FINAL_ANSWER)
            )

    def test_broadcast_and_direct_membership(self) -> None:
        broadcast = _message(recipient="team")
        assert _policy().authorize(broadcast) is broadcast
        with pytest.raises(MailboxPermissionError, match="not a team member"):
            _policy().authorize(_message(sender="outsider", recipient="team"))

    def test_foreign_team_rejected(self) -> None:
        with pytest.raises(MailboxPermissionError, match="different team"):
            _policy().authorize(
                _message().model_copy(update={"team_id": "team-2"})
            )


class TestLimits:
    def test_body_is_bounded(self) -> None:
        with pytest.raises(ValidationError):
            _message(body="x" * 4097)

    def test_self_assignment_rejected(self) -> None:
        with pytest.raises(ValidationError, match="other than the sender"):
            _message(sender="lead", recipient="lead", kind=MessageKind.TASK_ASSIGNMENT)

    def test_frequency_bound_enforced(self) -> None:
        policy = FrequencyPolicy(window_seconds=60, max_per_window=2)
        prior = tuple(
            _message(subject=f"s{i}", sent_at=NOW - timedelta(seconds=i))
            for i in (5, 10)
        )
        with pytest.raises(Exception, match="exceeded"):
            policy.enforce("lead", _message(subject="new"), prior)

    def test_messages_outside_the_window_do_not_count(self) -> None:
        policy = FrequencyPolicy(window_seconds=60, max_per_window=2)
        prior = tuple(
            _message(subject=f"old{i}", sent_at=NOW - timedelta(seconds=120 + i))
            for i in (5, 10)
        )
        policy.enforce("lead", _message(subject="new"), prior)  # no raise


class TestDedup:
    def test_same_key_resolves_as_replay(self) -> None:
        first = _message(subject="task-a", kind=MessageKind.TASK_ASSIGNMENT)
        duplicate = first.model_copy(update={"message_id": f"msg-{uuid4()}"})
        assert dedup_resolution(duplicate, (first,)) == "replay"
        assert dedup_resolution(_message(subject="other"), (first,)) == "deliver"

    def test_dedup_key_is_stable_across_ids(self) -> None:
        first = _message()
        same_content = first.model_copy(update={"message_id": "msg-other"})
        assert first.dedup_key == same_content.dedup_key
