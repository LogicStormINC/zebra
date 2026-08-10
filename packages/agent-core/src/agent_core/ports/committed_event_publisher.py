from __future__ import annotations

from typing import Protocol

from agent_core.domain.events import SessionEvent


class CommittedEventPublisherPort(Protocol):
    """Publish a canonical Event only after its durable append commits."""

    def publish_committed(self, event: SessionEvent) -> None: ...
