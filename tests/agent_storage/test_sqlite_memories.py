from datetime import UTC, datetime, timedelta
from pathlib import Path

from agent_core.domain.identifiers import new_memory_id, new_session_id
from agent_core.domain.memories import (
    MemoryQuery,
    MemoryRecord,
    MemoryStatus,
    MemoryType,
    MemoryVisibility,
)
from agent_storage import (
    SQLiteMemoryStore,
    list_confirmed_repo_memories,
    list_confirmed_repo_memory_texts,
)


def test_sqlite_memory_store_roundtrips_repo_records_in_deterministic_order(
    tmp_path: Path,
) -> None:
    store = SQLiteMemoryStore(tmp_path / "memory.sqlite")
    older = _record(
        memory_type=MemoryType.PROCEDURE,
        text="Run make check before pushing.",
        visibility=MemoryVisibility.REPO,
        repo_id="zebra-agent",
        updated_at=_now(),
    )
    newer = _record(
        memory_type=MemoryType.PROJECT_RULE,
        text="This repo uses uv instead of Poetry.",
        visibility=MemoryVisibility.REPO,
        repo_id="zebra-agent",
        updated_at=_now() + timedelta(minutes=5),
    )

    store.upsert(older)
    store.upsert(newer)

    records = store.list(MemoryQuery(repo_id="zebra-agent"))

    assert [record.memory_id for record in records] == [newer.memory_id, older.memory_id]
    assert [record.text for record in records] == [
        "This repo uses uv instead of Poetry.",
        "Run make check before pushing.",
    ]


def test_sqlite_memory_store_updates_existing_record(tmp_path: Path) -> None:
    store = SQLiteMemoryStore(tmp_path / "update.sqlite")
    original = _record(
        memory_type=MemoryType.PROJECT_RULE,
        text="Keep session recovery event-driven.",
        visibility=MemoryVisibility.REPO,
        repo_id="zebra-agent",
        confidence=0.7,
        updated_at=_now(),
    )
    updated = original.model_copy(
        update={
            "text": "Keep working memory derived from session projections.",
            "confidence": 0.95,
            "status": MemoryStatus.CONFIRMED,
            "updated_at": _now() + timedelta(minutes=10),
        }
    )

    store.upsert(original)
    store.upsert(updated)
    records = store.list(MemoryQuery(repo_id="zebra-agent"))

    assert len(records) == 1
    assert records[0].text == "Keep working memory derived from session projections."
    assert records[0].confidence == 0.95
    assert records[0].status is MemoryStatus.CONFIRMED


def test_sqlite_memory_store_gets_record_by_id(tmp_path: Path) -> None:
    store = SQLiteMemoryStore(tmp_path / "get.sqlite")
    record = _record(
        memory_type=MemoryType.PROCEDURE,
        text="Run focused pytest first.",
        visibility=MemoryVisibility.REPO,
        repo_id="zebra-agent",
        status=MemoryStatus.CANDIDATE,
        updated_at=_now(),
    )

    store.upsert(record)

    loaded = store.get(record.memory_id)

    assert loaded == record


def test_sqlite_memory_store_filters_by_user_scope_and_status(tmp_path: Path) -> None:
    store = SQLiteMemoryStore(tmp_path / "user-scope.sqlite")
    confirmed = _record(
        memory_type=MemoryType.PREFERENCE,
        text="Prefer concise CLI output.",
        visibility=MemoryVisibility.USER,
        user_id="user-1",
        status=MemoryStatus.CONFIRMED,
        updated_at=_now(),
    )
    candidate = _record(
        memory_type=MemoryType.PREFERENCE,
        text="Maybe default to a separate review step.",
        visibility=MemoryVisibility.USER,
        user_id="user-1",
        status=MemoryStatus.CANDIDATE,
        updated_at=_now() + timedelta(minutes=1),
    )

    store.upsert(confirmed)
    store.upsert(candidate)

    confirmed_records = store.list(MemoryQuery(user_id="user-1"))
    candidate_records = store.list(
        MemoryQuery(user_id="user-1", statuses=(MemoryStatus.CANDIDATE,))
    )

    assert [record.memory_id for record in confirmed_records] == [confirmed.memory_id]
    assert [record.memory_id for record in candidate_records] == [candidate.memory_id]


def test_list_confirmed_repo_memory_texts_returns_confirmed_records_only(tmp_path: Path) -> None:
    store = SQLiteMemoryStore(tmp_path / "memory-texts.sqlite")
    store.upsert(
        _record(
            memory_type=MemoryType.PROJECT_RULE,
            text="Use uv instead of Poetry.",
            visibility=MemoryVisibility.REPO,
            repo_id="zebra-agent",
            status=MemoryStatus.CONFIRMED,
            updated_at=_now(),
        )
    )
    store.upsert(
        _record(
            memory_type=MemoryType.PROCEDURE,
            text="Run make check before push.",
            visibility=MemoryVisibility.REPO,
            repo_id="zebra-agent",
            status=MemoryStatus.CANDIDATE,
            updated_at=_now() + timedelta(minutes=1),
        )
    )

    texts = list_confirmed_repo_memory_texts(
        tmp_path / "memory-texts.sqlite",
        repo_id="zebra-agent",
    )

    assert texts == ("Use uv instead of Poetry.",)


def test_list_confirmed_repo_memories_ranks_and_deduplicates_records(
    tmp_path: Path,
) -> None:
    store = SQLiteMemoryStore(tmp_path / "memory-ranked.sqlite")
    store.upsert(
        _record(
            memory_type=MemoryType.PROCEDURE,
            text="Run make check before push.",
            visibility=MemoryVisibility.REPO,
            repo_id="zebra-agent",
            status=MemoryStatus.CONFIRMED,
            updated_at=_now(),
        )
    )
    store.upsert(
        _record(
            memory_type=MemoryType.PROJECT_RULE,
            text="Use uv instead of Poetry.",
            visibility=MemoryVisibility.REPO,
            repo_id="zebra-agent",
            status=MemoryStatus.CONFIRMED,
            updated_at=_now() + timedelta(minutes=1),
        )
    )
    store.upsert(
        _record(
            memory_type=MemoryType.PROCEDURE,
            text="Run   make check before push.",
            visibility=MemoryVisibility.REPO,
            repo_id="zebra-agent",
            status=MemoryStatus.CONFIRMED,
            updated_at=_now() + timedelta(minutes=2),
        )
    )
    store.upsert(
        _record(
            memory_type=MemoryType.ARCHITECTURE_FACT,
            text="Harness workers remain stateless.",
            visibility=MemoryVisibility.REPO,
            repo_id="zebra-agent",
            status=MemoryStatus.CONFIRMED,
            updated_at=_now() + timedelta(minutes=3),
        )
    )

    memories = list_confirmed_repo_memories(
        tmp_path / "memory-ranked.sqlite",
        repo_id="zebra-agent",
    )

    assert [(memory.memory_type, memory.text) for memory in memories] == [
        (MemoryType.PROJECT_RULE, "Use uv instead of Poetry."),
        (MemoryType.ARCHITECTURE_FACT, "Harness workers remain stateless."),
        (MemoryType.PROCEDURE, "Run   make check before push."),
    ]


def _record(
    *,
    memory_type: MemoryType,
    text: str,
    visibility: MemoryVisibility,
    updated_at: datetime,
    repo_id: str | None = None,
    user_id: str | None = None,
    status: MemoryStatus = MemoryStatus.CONFIRMED,
    confidence: float = 0.9,
) -> MemoryRecord:
    return MemoryRecord(
        memory_id=new_memory_id(),
        memory_type=memory_type,
        text=text,
        confidence=confidence,
        status=status,
        visibility=visibility,
        repo_id=repo_id,
        user_id=user_id,
        source_session_id=new_session_id(),
        source_event_start=1,
        source_event_end=3,
        created_at=_now(),
        updated_at=updated_at,
    )


def _now() -> datetime:
    return datetime(2026, 7, 2, 18, 30, tzinfo=UTC)
