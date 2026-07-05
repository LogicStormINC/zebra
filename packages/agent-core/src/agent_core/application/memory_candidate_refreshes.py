from __future__ import annotations

from dataclasses import dataclass

from agent_core.domain.memories import MemoryType


@dataclass(frozen=True)
class MemoryRefreshTarget:
    key: str
    memory_types: tuple[MemoryType, ...]
    reason: str
