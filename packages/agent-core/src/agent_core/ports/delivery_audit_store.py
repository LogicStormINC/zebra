from typing import Protocol

from agent_core.domain.delivery_audit import DeliveryAuditRecord
from agent_core.domain.identifiers import SessionId


class DeliveryAuditStorePort(Protocol):
    def append(self, record: DeliveryAuditRecord) -> DeliveryAuditRecord:
        raise NotImplementedError

    def list_for_session(self, session_id: SessionId) -> list[DeliveryAuditRecord]:
        raise NotImplementedError
