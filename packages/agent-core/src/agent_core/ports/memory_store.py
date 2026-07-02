from typing import Protocol

from agent_core.domain.memories import MemoryQuery, MemoryRecord


class MemoryStorePort(Protocol):
    def upsert(self, record: MemoryRecord) -> MemoryRecord: ...

    def list(self, query: MemoryQuery) -> list[MemoryRecord]: ...
