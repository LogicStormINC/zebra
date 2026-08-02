"""Ports for provider-neutral memory delivery state changes."""

from typing import Protocol

from agent_core.domain.memory_delivery import (
    MemoryDeliveryOperationRecord,
    MemoryDeliveryScope,
    MemoryDeliveryTransition,
)


class MemoryDeliveryLedgerPort(Protocol):
    """Apply fenced delivery transitions without exposing a storage backend."""

    def transition(
        self,
        request: MemoryDeliveryTransition,
    ) -> MemoryDeliveryOperationRecord: ...

    def quarantine_scope(
        self,
        scope: MemoryDeliveryScope,
        *,
        reason_code: str,
    ) -> MemoryDeliveryScope: ...
