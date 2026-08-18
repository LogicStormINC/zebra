from dataclasses import dataclass
from datetime import datetime
from typing import Protocol


@dataclass(frozen=True)
class IdempotencyRecord:
    action: str
    idempotency_key: str
    request_hash: str
    status_code: int
    response_body: dict[str, object]
    created_at: datetime


class IdempotencyStorePort(Protocol):
    def get(self, *, action: str, idempotency_key: str) -> IdempotencyRecord | None: ...

    def save(self, record: IdempotencyRecord) -> IdempotencyRecord: ...
