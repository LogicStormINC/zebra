from typing import Protocol

from agent_core.domain.identifiers import MemoryId
from agent_core.domain.memories import MemoryQuery, MemoryRecord


class MemoryStorePort(Protocol):
    def get(self, memory_id: MemoryId) -> MemoryRecord | None: ...

    def upsert(self, record: MemoryRecord) -> MemoryRecord: ...

    def list(self, query: MemoryQuery) -> list[MemoryRecord]: ...
