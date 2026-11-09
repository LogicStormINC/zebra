"""One prepared human input and its immutable native replay coordinates."""

from dataclasses import dataclass

from agent_core.domain.events import SessionEvent
from agent_core.domain.http_input_attachments import PreparedHttpInputBatch


@dataclass(frozen=True, slots=True)
class PreparedHttpInputMessage:
    event: SessionEvent
    attachments: PreparedHttpInputBatch
    action: str
    idempotency_key: str
    request_hash: str
