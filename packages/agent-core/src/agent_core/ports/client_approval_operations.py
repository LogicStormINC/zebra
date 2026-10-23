"""Exact approval receipts and a short atomic native decision boundary."""

from contextlib import AbstractContextManager
from typing import Protocol, runtime_checkable

from agent_core.domain.events import SessionEvent
from agent_core.domain.identifiers import SessionId


@runtime_checkable
class ClientApprovalOperationPort(Protocol):
    def approval_operation_unit(self, segment: SessionId) -> AbstractContextManager[None]: ...

    def read_approval_operation(self, segment: SessionId, key: str) -> SessionEvent | None: ...
