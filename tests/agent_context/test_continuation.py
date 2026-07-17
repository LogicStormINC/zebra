from datetime import UTC, datetime

from agent_context.continuation import select_context_continuation
from agent_core.domain.context_capsule import ContextCapsule
from agent_core.domain.context_continuation import (
    ProviderContinuationCapability,
    ProviderContinuationMode,
    ProviderContinuationRef,
)


def test_missing_provider_capability_uses_transparent_capsule_fallback() -> None:
    selected = select_context_continuation(object(), _capsule())

    assert selected.mode == "capsule_fallback"
    assert selected.reference is None


def test_provider_reference_is_accepted_only_for_matching_capsule_source() -> None:
    selected = select_context_continuation(_ProviderGateway(), _capsule())

    assert selected.mode == "provider_native"
    assert selected.reference is not None
    assert selected.reference.reference_id == "opaque-ref-1"


class _ProviderGateway:
    continuation_capability = ProviderContinuationCapability(
        mode=ProviderContinuationMode.OPAQUE_REFERENCE,
        recoverable_across_workers=True,
    )

    def compact_to_reference(self, capsule: ContextCapsule) -> ProviderContinuationRef:
        return ProviderContinuationRef(
            reference_id="opaque-ref-1",
            provider="provider",
            model_name="model",
            source_hash=capsule.source_hash,
        )


def _capsule() -> ContextCapsule:
    return ContextCapsule(
        capsule_id="ctxcap-test",
        objective="Keep working",
        immediate_next="Run tests",
        source_hash="a" * 64,
        confidence=0.9,
        created_at=datetime(2026, 7, 17, 10, 0, tzinfo=UTC),
    )
