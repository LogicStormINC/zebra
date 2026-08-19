"""Agent mailbox domain contracts (ORCH-MAILBOX-CON-01, plan Phase E).

Messages are bounded, deduplicated and permission-checked. Task
assignments, direct messages and final answers are first-class kinds;
the Team Lead is the only final-answer recipient. Size and frequency
limits are structural, not polite requests.
"""

from __future__ import annotations

import hashlib
from datetime import datetime
from enum import StrEnum
from typing import Literal, Self

from pydantic import BaseModel, ConfigDict, Field, model_validator

MAX_BODY_CHARS = 4096
MAX_SUBJECT_CHARS = 256
RATE_WINDOW_SECONDS = 60
DEFAULT_MAX_PER_WINDOW = 10
TEAM_BROADCAST = "team"


class MailboxPermissionError(ValueError):
    """Sender is not allowed to produce this message."""


class MailboxRateLimitError(ValueError):
    """Sender exceeded the frequency bound for the window."""


class MessageKind(StrEnum):
    TASK_ASSIGNMENT = "task_assignment"
    DIRECT_MESSAGE = "direct_message"
    FINAL_ANSWER = "final_answer"


class AgentMessage(BaseModel):
    """One durable mailbox message between team agents."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    message_id: str = Field(min_length=1, max_length=128)
    team_id: str = Field(min_length=1, max_length=128)
    sender: str = Field(min_length=1, max_length=128)
    recipient: str = Field(min_length=1, max_length=128)
    kind: MessageKind
    subject: str = Field(min_length=1, max_length=MAX_SUBJECT_CHARS)
    body: str = Field(default="", max_length=MAX_BODY_CHARS)
    sent_at: datetime

    @model_validator(mode="after")
    def _validate(self) -> Self:
        if self.sent_at.tzinfo is None:
            raise ValueError("message sent_at must be timezone-aware")
        if self.kind is MessageKind.TASK_ASSIGNMENT and self.sender == self.recipient:
            raise ValueError("a task assignment needs a recipient other than the sender")
        return self

    @property
    def dedup_key(self) -> str:
        canonical = (
            f"{self.team_id}|{self.sender}|{self.recipient}"
            f"|{self.kind.value}|{self.subject}"
        )
        return hashlib.sha256(canonical.encode()).hexdigest()


class MailboxPermissionPolicy(BaseModel):
    """Who may send what (plan: lead assigns; teammates answer the lead)."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    team_id: str
    lead: str = Field(min_length=1, max_length=128)
    members: frozenset[str] = Field(min_length=1)

    @model_validator(mode="after")
    def _validate(self) -> Self:
        if self.lead not in self.members:
            raise ValueError("the lead must be a member")
        return self

    def authorize(self, message: AgentMessage) -> AgentMessage:
        if message.team_id != self.team_id:
            raise MailboxPermissionError("message targets a different team")
        if message.sender not in self.members:
            raise MailboxPermissionError("sender is not a team member")
        if message.kind is MessageKind.TASK_ASSIGNMENT and message.sender != self.lead:
            raise MailboxPermissionError("only the lead assigns tasks")
        if message.kind is MessageKind.TASK_ASSIGNMENT and message.recipient not in self.members:
            raise MailboxPermissionError("assignment targets a non-member")
        if message.kind is MessageKind.DIRECT_MESSAGE:
            if message.recipient != TEAM_BROADCAST and message.recipient not in self.members:
                raise MailboxPermissionError("direct message targets a non-member")
        if message.kind is MessageKind.FINAL_ANSWER:
            if message.recipient != self.lead:
                raise MailboxPermissionError("final answers go to the lead only")
            if message.sender == self.lead:
                raise MailboxPermissionError("the lead does not send final answers")
        return message


class FrequencyPolicy(BaseModel):
    """Bounded send rate per sender inside a sliding window."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    window_seconds: int = Field(default=RATE_WINDOW_SECONDS, ge=1)
    max_per_window: int = Field(default=DEFAULT_MAX_PER_WINDOW, ge=1)

    def enforce(
        self,
        sender: str,
        candidate: AgentMessage,
        prior: tuple[AgentMessage, ...],
    ) -> None:
        window_start = candidate.sent_at.timestamp() - self.window_seconds
        recent = [
            message
            for message in prior
            if message.sender == sender
            and message.sent_at.timestamp() >= window_start
            and message.sent_at.timestamp() <= candidate.sent_at.timestamp()
        ]
        if len(recent) >= self.max_per_window:
            raise MailboxRateLimitError(
                f"{sender} exceeded {self.max_per_window} messages "
                f"per {self.window_seconds}s"
            )


def dedup_resolution(
    incoming: AgentMessage,
    existing: tuple[AgentMessage, ...],
) -> Literal["deliver", "replay"]:
    """Same dedup key resolves as a replay — never a second delivery."""

    for message in existing:
        if message.dedup_key == incoming.dedup_key:
            return "replay"
    return "deliver"
