from dataclasses import dataclass
from datetime import datetime
from typing import Protocol

from agent_core.domain.context_capsule import ContextCapsule
from agent_core.domain.messages import SessionMessage


@dataclass(frozen=True)
class ConversationCompactionResult:
    messages: tuple[SessionMessage, ...]
    before_tokens: int
    after_tokens: int
    removed_message_count: int
    retained_message_count: int
    compacted: bool
    within_budget: bool
    provenance: str
    capsule: ContextCapsule | None = None
    recovery_messages: tuple[SessionMessage, ...] | None = None

    def __post_init__(self) -> None:
        if self.before_tokens < 0 or self.after_tokens < 0:
            raise ValueError("conversation token estimates cannot be negative")
        if self.removed_message_count < 0 or self.retained_message_count < 0:
            raise ValueError("conversation message counts cannot be negative")
        if not self.provenance.strip():
            raise ValueError("conversation compaction provenance must not be blank")


class ConversationCompactorPort(Protocol):
    def compact_conversation(
        self,
        messages: tuple[SessionMessage, ...],
        *,
        user_goal: str,
        max_tokens: int,
        created_at: datetime,
    ) -> ConversationCompactionResult: ...
