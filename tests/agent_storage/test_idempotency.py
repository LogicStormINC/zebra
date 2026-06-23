from pathlib import Path

from agent_storage import (
    IdempotencyConflictError,
    SQLiteIdempotencyStore,
    new_idempotency_record,
)


def test_sqlite_idempotency_store_saves_and_reads_record(tmp_path: Path) -> None:
    store = SQLiteIdempotencyStore(tmp_path / "idempotency.sqlite")
    record = new_idempotency_record(
        action="session.commit",
        idempotency_key="commit-1",
        request_hash="hash-1",
        status_code=201,
        response_body={"commit_sha": "abc", "idempotency_key": "commit-1"},
    )

    store.save(record)
    loaded = store.get(action="session.commit", idempotency_key="commit-1")

    assert loaded == record


def test_sqlite_idempotency_store_reuses_same_hash_record(tmp_path: Path) -> None:
    store = SQLiteIdempotencyStore(tmp_path / "idempotency.sqlite")
    record = new_idempotency_record(
        action="session.commit",
        idempotency_key="commit-1",
        request_hash="hash-1",
        status_code=201,
        response_body={"commit_sha": "abc", "idempotency_key": "commit-1"},
    )

    store.save(record)
    loaded = store.save(
        new_idempotency_record(
            action="session.commit",
            idempotency_key="commit-1",
            request_hash="hash-1",
            status_code=409,
            response_body={"status": "would_not_replace"},
        )
    )

    assert loaded == record


def test_sqlite_idempotency_store_rejects_same_key_different_hash(tmp_path: Path) -> None:
    store = SQLiteIdempotencyStore(tmp_path / "idempotency.sqlite")
    store.save(
        new_idempotency_record(
            action="session.commit",
            idempotency_key="commit-1",
            request_hash="hash-1",
            status_code=201,
            response_body={"commit_sha": "abc", "idempotency_key": "commit-1"},
        )
    )

    try:
        store.save(
            new_idempotency_record(
                action="session.commit",
                idempotency_key="commit-1",
                request_hash="hash-2",
                status_code=201,
                response_body={"commit_sha": "def", "idempotency_key": "commit-1"},
            )
        )
    except IdempotencyConflictError as error:
        assert str(error) == "idempotency key reused with different request"
    else:
        raise AssertionError("expected idempotency conflict")
