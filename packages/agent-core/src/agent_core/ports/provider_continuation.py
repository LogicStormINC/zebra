from typing import Protocol, runtime_checkable

from agent_core.domain.context_capsule import ContextCapsule
from agent_core.domain.context_continuation import (
    ProviderContinuationCapability,
    ProviderContinuationRef,
)


@runtime_checkable
class ProviderContinuationPort(Protocol):
    @property
    def continuation_capability(self) -> ProviderContinuationCapability: ...

    def compact_to_reference(self, capsule: ContextCapsule) -> ProviderContinuationRef: ...
