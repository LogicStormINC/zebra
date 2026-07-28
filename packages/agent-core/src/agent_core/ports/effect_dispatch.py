from datetime import timedelta
from typing import Protocol
from uuid import UUID

from agent_core.domain.effect_dispatch import (
    EffectClaim,
    EffectDispatch,
    EffectEvidence,
    EffectResolutionOutcome,
    EffectScheduleRequest,
)
from agent_core.domain.events import SessionEvent
from agent_core.domain.identifiers import SessionId
from agent_core.domain.leases import LeaseFence
from agent_core.domain.tools import ToolResult


class EffectDispatchPort(Protocol):
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

    def list_reconcilable(
        self,
        execution_session_id: SessionId,
        *,
        current_fence: LeaseFence,
        limit: int = 100,
    ) -> tuple[EffectClaim, ...]: ...

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
