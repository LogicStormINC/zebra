"""Dispatch port for durable client effects (schedule-only semantics)."""

from dataclasses import dataclass
from typing import Protocol

from agent_core.domain.client_effects import (
    ClientEffectContinuation,
    ClientEffectRequest,
)
from agent_core.domain.identifiers import ClientEffectId, ClientSessionId


@dataclass(frozen=True)
class ClientEffectScheduleOutcome:
    effect: ClientEffectRequest
    created: bool


class ClientEffectDispatchPort(Protocol):
    def schedule(
        self,
        request: ClientEffectRequest,
        *,
        continuation: ClientEffectContinuation,
    ) -> ClientEffectScheduleOutcome:
        """Persist request + continuation + scheduled event in one transaction."""

    def get_effect(self, effect_id: ClientEffectId) -> ClientEffectRequest | None: ...

    def list_pending(
        self, client_session_id: ClientSessionId, *, limit: int = 50
    ) -> tuple[ClientEffectRequest, ...]:
        """Bounded pending query for reconnect replay."""

    def mark_delivered(self, effect_id: ClientEffectId) -> None: ...
