from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

from agent_core.domain.memories import MemoryQuery, MemoryStatus, MemoryType, MemoryVisibility
from agent_core.ports.context_compiler import ConfirmedMemoryInput
from agent_core.ports.memory_store import MemoryStorePort

from agent_storage.memories import SQLiteMemoryStore

_TYPE_PRIORITY: dict[MemoryType, int] = {
    MemoryType.PROJECT_RULE: 0,
    MemoryType.ARCHITECTURE_FACT: 1,
    MemoryType.PROCEDURE: 2,
    MemoryType.PREFERENCE: 3,
    MemoryType.EPISODIC: 4,
    MemoryType.FAILED_ATTEMPT: 5,
}


def list_confirmed_repo_memories(
    store_or_database_path: MemoryStorePort | str | Path,
    *,
    repo_id: str,
    limit: int = 8,
    as_of: datetime | None = None,
) -> tuple[ConfirmedMemoryInput, ...]:
    effective_as_of = as_of or datetime.now(UTC)
    records = _memory_store(store_or_database_path).list(
        MemoryQuery(
            repo_id=repo_id,
            visibility=MemoryVisibility.REPO,
            statuses=(MemoryStatus.CONFIRMED,),
            limit=500,
        )
    )
    ranked = sorted(
        records,
        key=lambda record: (
            _TYPE_PRIORITY.get(record.memory_type, len(_TYPE_PRIORITY)),
            -record.updated_at.timestamp(),
            -record.created_at.timestamp(),
            str(record.memory_id),
        ),
    )
    unique: list[ConfirmedMemoryInput] = []
    seen: set[tuple[MemoryType, str]] = set()
    for record in ranked:
        if record.expires_at is not None and record.expires_at <= effective_as_of:
            continue
        key = (record.memory_type, _normalize_memory_text(record.text))
        if key in seen:
            continue
        seen.add(key)
        unique.append(
            ConfirmedMemoryInput(
                memory_type=record.memory_type,
                text=record.text,
            )
        )
        if len(unique) >= limit:
            break
    return tuple(unique)


def list_confirmed_repo_memory_texts(
    store_or_database_path: MemoryStorePort | str | Path,
    *,
    repo_id: str,
    limit: int = 8,
    as_of: datetime | None = None,
) -> tuple[str, ...]:
    return tuple(
        memory.text
        for memory in list_confirmed_repo_memories(
            store_or_database_path,
            repo_id=repo_id,
            limit=limit,
            as_of=as_of,
        )
    )


def _memory_store(source: MemoryStorePort | str | Path) -> MemoryStorePort:
    return SQLiteMemoryStore(source) if isinstance(source, str | Path) else source


def _normalize_memory_text(text: str) -> str:
    return " ".join(text.strip().split())
