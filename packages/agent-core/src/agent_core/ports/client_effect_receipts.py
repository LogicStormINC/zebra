"""Receipt port: atomic receipt acceptance plus parent resume command."""

from dataclasses import dataclass
from typing import Protocol

from agent_core.domain.client_effects import ClientEffectReceipt, ClientEffectRequest
from agent_core.domain.identifiers import SessionId


@dataclass(frozen=True)
class ClientReceiptAcceptance:
    receipt: ClientEffectReceipt
    effect: ClientEffectRequest
    resume_command_id: str | None
    replayed: bool


class ClientEffectReceiptPort(Protocol):
    def accept_receipt(
        self,
        receipt: ClientEffectReceipt,
        *,
        request_fence_hash: str,
        session_id: SessionId,
    ) -> ClientReceiptAcceptance:
        """Validate fence/revision/expiry, then commit receipt + terminal
        status + parent resume command atomically; replays return the
        stored acceptance without a second command."""
