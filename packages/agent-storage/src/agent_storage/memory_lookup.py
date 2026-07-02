from __future__ import annotations

from pathlib import Path

from agent_core.domain.memories import MemoryQuery, MemoryStatus, MemoryType, MemoryVisibility
from agent_core.ports.context_compiler import ConfirmedMemoryInput

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
    database_path: str | Path,
    *,
    repo_id: str,
    limit: int = 8,
) -> tuple[ConfirmedMemoryInput, ...]:
    records = SQLiteMemoryStore(database_path).list(
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
    database_path: str | Path,
    *,
    repo_id: str,
    limit: int = 8,
) -> tuple[str, ...]:
    return tuple(
        memory.text
        for memory in list_confirmed_repo_memories(
            database_path,
            repo_id=repo_id,
            limit=limit,
        )
    )


def _normalize_memory_text(text: str) -> str:
    return " ".join(text.strip().split())
