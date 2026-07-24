from dataclasses import dataclass
from enum import StrEnum
from typing import Protocol

from agent_core.domain.identifiers import SessionId
from agent_core.domain.session_handoff import EffectIdentity
from agent_core.domain.tools import ToolResult


class EffectLedgerStatus(StrEnum):
    RESERVED = "reserved"
    EXECUTING = "executing"
    SUCCEEDED = "succeeded"
    FAILED_NO_EFFECT = "failed_no_effect"
    UNCERTAIN = "uncertain"


@dataclass(frozen=True, slots=True)
class EffectReservation:
    root_session_id: SessionId
    identity: EffectIdentity
    status: EffectLedgerStatus
    attempt: int
    result: ToolResult | None = None
    replay: bool = False


class EffectLedgerPort(Protocol):
    def reserve(
        self,
        root_session_id: SessionId,
        identity: EffectIdentity,
        *,
        explicit_retry: bool = False,
    ) -> EffectReservation: ...

    def mark_executing(self, reservation: EffectReservation) -> None: ...

    def mark_succeeded(self, reservation: EffectReservation, result: ToolResult) -> None: ...

    def mark_failed_no_effect(self, reservation: EffectReservation) -> None: ...

    def mark_uncertain(self, reservation: EffectReservation) -> None: ...

    def terminal_keys(self, root_session_id: SessionId) -> frozenset[str]: ...

    def has_uncertain(self, root_session_id: SessionId) -> bool: ...
