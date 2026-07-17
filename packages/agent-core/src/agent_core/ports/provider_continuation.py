from typing import Protocol, runtime_checkable

from agent_core.domain.context_capsule import ContextCapsule
from agent_core.domain.context_continuation import (
    ProviderContinuationCapability,
    ProviderContinuationRef,
)
from agent_core.domain.messages import SessionMessage
from agent_core.domain.modeling import ModelCompletion, ModelToolDefinition


@runtime_checkable
class ProviderContinuationPort(Protocol):
    @property
    def continuation_capability(self) -> ProviderContinuationCapability: ...

    def compact_to_reference(self, capsule: ContextCapsule) -> ProviderContinuationRef: ...


@runtime_checkable
class ProviderContinuationPayloadPort(Protocol):
    def export_continuation_payload(self, reference: ProviderContinuationRef) -> bytes: ...


@runtime_checkable
class ProviderContinuationCompletionPort(Protocol):
    def complete_from_reference(
        self,
        reference: ProviderContinuationRef,
        messages: list[SessionMessage],
        *,
        tools: tuple[ModelToolDefinition, ...] = (),
    ) -> ModelCompletion: ...
