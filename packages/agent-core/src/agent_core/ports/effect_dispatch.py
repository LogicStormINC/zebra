from datetime import timedelta
from typing import Protocol
from uuid import UUID

from pydantic import BaseModel

from agent_core.domain.effect_dispatch import (
    EffectClaim,
    EffectDispatch,
    EffectDispatchStateError,
    EffectEvidence,
    EffectResolutionOutcome,
    EffectScheduleRequest,
)
from agent_core.domain.events import SessionEvent
from agent_core.domain.identifiers import SessionId
from agent_core.domain.leases import LeaseFence
from agent_core.domain.tools import ToolResult


def effect_input(value: object) -> object:
    """Expose original recursive fields so exact execution never trusts typed copies."""
    if isinstance(value, BaseModel):
        if value.__pydantic_extra__ or value.__dict__.keys() - type(value).model_fields.keys():
            raise EffectDispatchStateError("exact Effect input carries unsupported attributes")
        return effect_input(value.__dict__)
    if isinstance(value, dict):
        return {key: effect_input(item) for key, item in value.items()}
    if isinstance(value, tuple):
        return tuple(effect_input(item) for item in value)
    if isinstance(value, list):
        return [effect_input(item) for item in value]
    return value


class EffectDispatchPort(Protocol):
    def read_intent_event(self, dispatch: EffectDispatch) -> SessionEvent: ...

    def schedule(
        self,
        request: EffectScheduleRequest,
        *,
        fence: LeaseFence,
    ) -> EffectDispatch: ...

    def claim_next(
        self,
        execution_session_id: SessionId,
        *,
        fence: LeaseFence,
        claim_ttl: timedelta,
    ) -> EffectClaim | None: ...

    def claim_exact(
        self,
        execution_session_id: SessionId,
        *,
        expected: EffectDispatch,
        fence: LeaseFence,
        claim_ttl: timedelta,
    ) -> EffectClaim | None:
        """Atomically claim only the matching pending durable dispatch.

        expected is the authoritative schedule result, not a caller-created ID
        selector. Missing, foreign, changed or nonpending rows cause no writes.
        """
        ...

    def list_reconcilable(
        self,
        execution_session_id: SessionId,
        *,
        current_fence: LeaseFence,
        limit: int = 100,
    ) -> tuple[EffectClaim, ...]: ...

    def list_uncertain(
        self,
        execution_session_id: SessionId,
        *,
        current_fence: LeaseFence,
        limit: int = 100,
    ) -> tuple[EffectDispatch, ...]: ...

    def complete(
        self,
        claim: EffectClaim,
        *,
        result: ToolResult,
        terminal_event: SessionEvent,
    ) -> SessionEvent: ...

    def fail_no_effect(
        self,
        claim: EffectClaim,
        *,
        evidence: EffectEvidence,
        terminal_event: SessionEvent,
    ) -> SessionEvent: ...

    def mark_uncertain(
        self,
        claim: EffectClaim,
        *,
        evidence: EffectEvidence,
        terminal_event: SessionEvent,
    ) -> SessionEvent: ...

    def reconcile_expired(
        self,
        dispatch_id: UUID,
        *,
        old_claim: EffectClaim,
        current_fence: LeaseFence,
        evidence: EffectEvidence,
    ) -> EffectDispatch: ...

    def resolve_uncertain(
        self,
        dispatch_id: UUID,
        *,
        current_fence: LeaseFence,
        evidence: EffectEvidence,
        outcome: EffectResolutionOutcome,
        terminal_event: SessionEvent,
        result: ToolResult | None = None,
    ) -> SessionEvent: ...

    def retry_failed_no_effect(
        self,
        dispatch_id: UUID,
        *,
        current_fence: LeaseFence,
        retry_key: str,
        started_event: SessionEvent,
    ) -> EffectDispatch: ...

    def mark_dead_letter(
        self,
        dispatch_id: UUID,
        *,
        current_fence: LeaseFence,
        evidence: EffectEvidence,
        terminal_event: SessionEvent,
    ) -> SessionEvent: ...
