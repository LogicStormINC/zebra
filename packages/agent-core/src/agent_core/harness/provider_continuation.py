from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from agent_core.domain.context_capsule import ContextCapsule
from agent_core.domain.context_continuation import (
    ProviderContinuationMode,
    ProviderContinuationRef,
)
from agent_core.domain.events import EventActor, EventType
from agent_core.harness.models import HarnessEventDraft
from agent_core.ports.provider_continuation import (
    ProviderContinuationPayloadPort,
    ProviderContinuationPort,
)


@dataclass(frozen=True)
class PreparedProviderContinuation:
    mode: str
    reason: str
    reference: ProviderContinuationRef | None = None
    artifact_id: str | None = None


def prepare_provider_continuation(
    gateway: object,
    capsule: ContextCapsule,
    persist: Callable[[ProviderContinuationRef, bytes | None, int | None], str | None]
    | None,
) -> PreparedProviderContinuation:
    if not isinstance(gateway, ProviderContinuationPort):
        return _fallback("provider capability unavailable")
    capability = gateway.continuation_capability
    if capability.mode is not ProviderContinuationMode.OPAQUE_REFERENCE:
        return _fallback("provider continuation disabled")
    try:
        reference = gateway.compact_to_reference(capsule)
    except (NotImplementedError, TimeoutError, ValueError):
        return _fallback("provider continuation failed")
    if (
        reference.source_hash != capsule.source_hash
        or reference.capability_version != capability.capability_version
    ):
        return _fallback("provider reference incompatible")
    payload = None
    if isinstance(gateway, ProviderContinuationPayloadPort):
        try:
            payload = gateway.export_continuation_payload(reference)
        except (NotImplementedError, TimeoutError, ValueError):
            return _fallback("provider payload export failed")
        if not payload:
            return _fallback("provider payload is empty")
        if reference.expires_at is None:
            return _fallback("provider payload expiry is required")
    try:
        artifact_id = (
            persist(reference, payload, capability.maximum_ttl_seconds)
            if persist is not None
            else None
        )
    except (TimeoutError, ValueError):
        return _fallback("provider continuation persistence failed")
    return PreparedProviderContinuation(
        mode="provider_native",
        reason="provider reference accepted",
        reference=reference,
        artifact_id=artifact_id,
    )


def continuation_event(
    selection: PreparedProviderContinuation,
    *,
    attempt_number: int,
) -> HarnessEventDraft:
    payload: dict[str, object] = {
        "attempt_number": attempt_number,
        "mode": selection.mode,
        "reason": selection.reason,
    }
    if selection.reference is not None:
        payload.update(
            {
                "reference_id": selection.reference.reference_id,
                "provider": selection.reference.provider,
                "model_name": selection.reference.model_name,
                "capability_version": selection.reference.capability_version,
                "source_hash": selection.reference.source_hash,
            }
        )
    if selection.artifact_id is not None:
        payload["artifact_id"] = selection.artifact_id
    return HarnessEventDraft(
        event_type=EventType.CONTEXT_CONTINUATION_SELECTED,
        actor=EventActor.HARNESS,
        payload=payload,
    )


def _fallback(reason: str) -> PreparedProviderContinuation:
    return PreparedProviderContinuation(mode="capsule_fallback", reason=reason)
