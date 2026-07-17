from dataclasses import dataclass

from agent_core.domain.context_capsule import ContextCapsule
from agent_core.domain.context_continuation import (
    ProviderContinuationMode,
    ProviderContinuationRef,
)
from agent_core.ports.provider_continuation import ProviderContinuationPort


@dataclass(frozen=True)
class ContinuationSelection:
    mode: str
    reason: str
    reference: ProviderContinuationRef | None = None


def select_context_continuation(
    gateway: object,
    capsule: ContextCapsule,
) -> ContinuationSelection:
    if not isinstance(gateway, ProviderContinuationPort):
        return ContinuationSelection("capsule_fallback", "provider capability unavailable")
    capability = gateway.continuation_capability
    if capability.mode is not ProviderContinuationMode.OPAQUE_REFERENCE:
        return ContinuationSelection("capsule_fallback", "provider continuation disabled")
    try:
        reference = gateway.compact_to_reference(capsule)
    except (NotImplementedError, TimeoutError, ValueError):
        return ContinuationSelection("capsule_fallback", "provider continuation failed")
    if reference.source_hash != capsule.source_hash:
        return ContinuationSelection("capsule_fallback", "provider reference source mismatch")
    return ContinuationSelection("provider_native", "provider reference accepted", reference)
