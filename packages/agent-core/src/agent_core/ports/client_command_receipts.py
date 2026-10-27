"""Bounded observation of an existing admission; absence never proves noncommit."""

from dataclasses import dataclass
from typing import Protocol, runtime_checkable
from uuid import UUID

from agent_core.domain.identifiers import ClientSessionId, SessionId, TaskId


@dataclass(frozen=True)
class ClientCommandReceipt:
    command_id: UUID

    def __post_init__(self) -> None:
        if not self.command_id.int:
            raise ValueError("invalid admitted command identity")


@runtime_checkable
class ClientCommandReceiptReadPort(Protocol):
    def read_client_command_receipt(
        self,
        segment_id: SessionId,
        key: str,
        task_id: TaskId,
        run_id: str,
        client_session_id: ClientSessionId,
    ) -> ClientCommandReceipt | None: ...
