import sqlite3
from datetime import UTC, datetime, timedelta
from pathlib import Path

from agent_core.domain.identifiers import SessionId, new_memory_id, new_session_id
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


def test_sqlite_memory_store_filters_session_before_applying_limit(tmp_path: Path) -> None:
    store = SQLiteMemoryStore(tmp_path / "session-scope.sqlite")
    target_session_id = new_session_id()
    target = _record(
        memory_type=MemoryType.PROCEDURE,
        text="Target session candidate.",
        visibility=MemoryVisibility.REPO,
        repo_id="zebra-agent",
        status=MemoryStatus.CANDIDATE,
        source_session_id=target_session_id,
        updated_at=_now(),
    )
    store.upsert(target)
    for index in range(500):
        store.upsert(
            _record(
                memory_type=MemoryType.PROCEDURE,
                text=f"Newer candidate {index} for another session.",
                visibility=MemoryVisibility.REPO,
                repo_id="zebra-agent",
                status=MemoryStatus.CANDIDATE,
                updated_at=_now() + timedelta(seconds=index + 1),
            )
        )

    records = store.list(
        MemoryQuery(
            repo_id="zebra-agent",
            source_session_id=target_session_id,
            statuses=(MemoryStatus.CANDIDATE,),
            limit=500,
        )
    )

    assert [record.memory_id for record in records] == [target.memory_id]


def test_sqlite_memory_store_fts_ranks_current_query_and_isolates_repo(
    tmp_path: Path,
) -> None:
    store = SQLiteMemoryStore(tmp_path / "fts.sqlite")
    relevant = _record(
        memory_type=MemoryType.PROCEDURE,
        text="Run pytest for context compaction regressions.",
        visibility=MemoryVisibility.REPO,
        repo_id="zebra-agent",
        updated_at=_now(),
    )
    unrelated = _record(
        memory_type=MemoryType.PROCEDURE,
        text="Build desktop assets with pnpm.",
        visibility=MemoryVisibility.REPO,
        repo_id="zebra-agent",
        updated_at=_now() + timedelta(minutes=1),
    )
    other_repo = _record(
        memory_type=MemoryType.PROCEDURE,
        text="Run pytest for context compaction regressions.",
        visibility=MemoryVisibility.REPO,
        repo_id="other-repo",
        updated_at=_now() + timedelta(minutes=2),
    )
    for record in (relevant, unrelated, other_repo):
        store.upsert(record)

    records = store.list(
        MemoryQuery(repo_id="zebra-agent", text_query="pytest context compaction")
    )

    assert [record.memory_id for record in records] == [relevant.memory_id]


def test_sqlite_memory_store_backfills_and_updates_fts_rows(tmp_path: Path) -> None:
    database = tmp_path / "fts-migration.sqlite"
    record = _record(
        memory_type=MemoryType.PROCEDURE,
        text="Run old validation command.",
        visibility=MemoryVisibility.REPO,
        repo_id="zebra-agent",
        updated_at=_now(),
    )
    store = SQLiteMemoryStore(database)
    store.upsert(record)
    with sqlite3.connect(database) as connection:
        connection.execute("DROP TABLE memory_records_fts")

    migrated = SQLiteMemoryStore(database)
    assert migrated.list(MemoryQuery(repo_id="zebra-agent", text_query="old validation"))

    migrated.upsert(
        record.model_copy(
            update={
                "text": "Run new focused regression command.",
                "updated_at": _now() + timedelta(minutes=1),
            }
        )
    )

    assert migrated.list(MemoryQuery(repo_id="zebra-agent", text_query="old validation")) == []
    updated = migrated.list(
        MemoryQuery(repo_id="zebra-agent", text_query="focused regression")
    )
    assert [item.memory_id for item in updated] == [record.memory_id]


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


def test_list_confirmed_repo_memories_skips_expired_records(tmp_path: Path) -> None:
    store = SQLiteMemoryStore(tmp_path / "memory-freshness.sqlite")
    store.upsert(
        _record(
            memory_type=MemoryType.PROJECT_RULE,
            text="Expired rule.",
            visibility=MemoryVisibility.REPO,
            repo_id="zebra-agent",
            status=MemoryStatus.CONFIRMED,
            updated_at=_now(),
            expires_at=_now() + timedelta(minutes=5),
        )
    )
    store.upsert(
        _record(
            memory_type=MemoryType.PROCEDURE,
            text="Fresh procedure.",
            visibility=MemoryVisibility.REPO,
            repo_id="zebra-agent",
            status=MemoryStatus.CONFIRMED,
            updated_at=_now() + timedelta(minutes=1),
            expires_at=_now() + timedelta(minutes=30),
        )
    )

    memories = list_confirmed_repo_memories(
        tmp_path / "memory-freshness.sqlite",
        repo_id="zebra-agent",
        as_of=_now() + timedelta(minutes=10),
    )

    assert [(memory.memory_type, memory.text) for memory in memories] == [
        (MemoryType.PROCEDURE, "Fresh procedure."),
    ]


def test_list_confirmed_repo_memories_combines_stable_and_relevant_with_token_cap(
    tmp_path: Path,
) -> None:
    store = SQLiteMemoryStore(tmp_path / "memory-relevant.sqlite")
    store.upsert(
        _record(
            memory_type=MemoryType.PROJECT_RULE,
            text="Keep agent-core provider neutral.",
            visibility=MemoryVisibility.REPO,
            repo_id="zebra-agent",
            updated_at=_now(),
        )
    )
    store.upsert(
        _record(
            memory_type=MemoryType.PROCEDURE,
            text="Run pytest for context compaction regressions.",
            visibility=MemoryVisibility.REPO,
            repo_id="zebra-agent",
            updated_at=_now() + timedelta(minutes=1),
        )
    )
    store.upsert(
        _record(
            memory_type=MemoryType.PROCEDURE,
            text="Build unrelated desktop release assets.",
            visibility=MemoryVisibility.REPO,
            repo_id="zebra-agent",
            updated_at=_now() + timedelta(minutes=2),
        )
    )

    memories = list_confirmed_repo_memories(
        tmp_path / "memory-relevant.sqlite",
        repo_id="zebra-agent",
        query_text="fix context compaction pytest",
        max_tokens=30,
    )

    assert [memory.text for memory in memories] == [
        "Keep agent-core provider neutral.",
        "Run pytest for context compaction regressions.",
    ]
    assert sum((len(memory.text) + 3) // 4 for memory in memories) <= 30


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
    expires_at: datetime | None = None,
    source_session_id: SessionId | None = None,
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
        source_session_id=source_session_id or new_session_id(),
        source_event_start=1,
        source_event_end=3,
        expires_at=expires_at,
        created_at=_now(),
        updated_at=updated_at,
    )


def _now() -> datetime:
    return datetime(2026, 7, 2, 18, 30, tzinfo=UTC)
