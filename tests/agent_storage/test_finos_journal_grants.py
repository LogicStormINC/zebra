from __future__ import annotations

import sqlite3
from datetime import UTC, datetime, timedelta
from hashlib import sha256
from pathlib import Path

import pytest
from agent_core.domain.identifiers import TaskId, new_task_id
from agent_storage import FinosJournalGrant, SQLiteFinosJournalGrantStore


def test_rotation_rejects_another_tasks_grant_without_changing_bindings(tmp_path: Path) -> None:
    store = SQLiteFinosJournalGrantStore(tmp_path / "tasks.sqlite")
    first_task, second_task = new_task_id(), new_task_id()
    expiry = datetime.now(UTC) + timedelta(minutes=10)
    store.bind(_grant(first_task, "grant-1", expiry))
    store.bind(_grant(second_task, "grant-2", expiry))

    with pytest.raises(ValueError):
        store.bind(_grant(first_task, "grant-2", expiry))

    assert _stored_grant(store, first_task) == "grant-1"
    assert _stored_grant(store, second_task) == "grant-2"


def test_rotation_rejects_retired_grant_replay_and_keeps_latest(tmp_path: Path) -> None:
    store = SQLiteFinosJournalGrantStore(tmp_path / "tasks.sqlite")
    task_id = new_task_id()
    expiry = datetime.now(UTC) + timedelta(minutes=10)
    store.bind(_grant(task_id, "grant-1", expiry))
    store.bind(_grant(task_id, "grant-2", expiry))

    with pytest.raises(ValueError):
        store.bind(_grant(task_id, "grant-1", expiry))

    assert _stored_grant(store, task_id) == "grant-2"


def test_rotation_accepts_a_new_grant_with_the_same_expiry(tmp_path: Path) -> None:
    store = SQLiteFinosJournalGrantStore(tmp_path / "tasks.sqlite")
    task_id = new_task_id()
    expiry = datetime.now(UTC) + timedelta(minutes=10)
    store.bind(_grant(task_id, "grant-1", expiry))

    store.bind(_grant(task_id, "grant-2", expiry))

    assert _stored_grant(store, task_id) == "grant-2"


def test_current_grant_is_idempotent(tmp_path: Path) -> None:
    store = SQLiteFinosJournalGrantStore(tmp_path / "tasks.sqlite")
    task_id = new_task_id()
    binding = _grant(task_id, "grant-1", datetime.now(UTC) + timedelta(minutes=10))
    store.bind(binding)

    store.bind(binding)

    assert _stored_grant(store, task_id) == "grant-1"


def test_model_tool_selection_survives_an_omitted_grant_rotation(tmp_path: Path) -> None:
    store = SQLiteFinosJournalGrantStore(tmp_path / "tasks.sqlite")
    task_id = new_task_id()
    expiry = datetime.now(UTC) + timedelta(minutes=10)
    selected = ("provider.records.list", "provider.records.get")
    store.bind(_grant(task_id, "grant-1", expiry, model_tool_names=selected))

    store.bind(_grant(task_id, "grant-2", expiry + timedelta(minutes=1)))

    binding = store.get(task_id)
    assert binding is not None
    assert binding.grant == "grant-2"
    assert binding.model_tool_names == selected


def test_existing_binding_is_registered_by_digest_before_rotation(tmp_path: Path) -> None:
    database = tmp_path / "legacy.sqlite"
    task_id = new_task_id()
    expiry = datetime.now(UTC) + timedelta(minutes=10)
    _seed_legacy(database, _grant(task_id, "legacy-grant", expiry))

    store = SQLiteFinosJournalGrantStore(database)

    with sqlite3.connect(database) as connection:
        digest_row = connection.execute(
            "SELECT grant_digest, task_id FROM finos_journal_grant_digests"
        ).fetchone()
    assert digest_row == (sha256(b"legacy-grant").hexdigest(), str(task_id))
    assert _stored_grant(store, task_id) == "legacy-grant"

    store.bind(_grant(task_id, "new-grant", expiry))
    with pytest.raises(ValueError):
        store.bind(_grant(task_id, "legacy-grant", expiry))
    assert _stored_grant(store, task_id) == "new-grant"


def test_conflicting_legacy_grant_fails_closed_and_each_task_can_recover(
    tmp_path: Path,
) -> None:
    database = tmp_path / "legacy-conflict.sqlite"
    first_task, second_task = new_task_id(), new_task_id()
    expiry = datetime.now(UTC) + timedelta(minutes=10)
    _seed_legacy(
        database,
        _grant(first_task, "shared-legacy-grant", expiry),
        _grant(second_task, "shared-legacy-grant", expiry),
    )

    store = SQLiteFinosJournalGrantStore(database)

    assert store.get(first_task) is None
    assert store.get(second_task) is None
    with pytest.raises(ValueError):
        store.bind(_grant(first_task, "shared-legacy-grant", expiry))
    with pytest.raises(ValueError):
        store.bind(_grant(second_task, "shared-legacy-grant", expiry))

    store.bind(_grant(first_task, "first-new-grant", expiry))
    assert _stored_grant(store, first_task) == "first-new-grant"
    assert store.get(second_task) is None
    store.bind(_grant(second_task, "second-new-grant", expiry))
    assert _stored_grant(store, second_task) == "second-new-grant"

    with sqlite3.connect(database) as connection:
        digest_rows = connection.execute(
            "SELECT grant_digest, task_id FROM finos_journal_grant_digests"
        ).fetchall()
    legacy_digest = sha256(b"shared-legacy-grant").hexdigest()
    legacy_owner = next(task_id for digest, task_id in digest_rows if digest == legacy_digest)
    assert legacy_owner not in {str(first_task), str(second_task)}
    assert "shared-legacy-grant" not in repr(digest_rows)


def _grant(
    task_id: TaskId,
    grant: str,
    expires_at: datetime,
    *,
    model_tool_names: tuple[str, ...] | None = None,
) -> FinosJournalGrant:
    return FinosJournalGrant(
        task_id=task_id,
        contract_version="finos.journals.v1",
        grant=grant,
        expires_at=expires_at,
        model_tool_names=model_tool_names,
    )


def _stored_grant(store: SQLiteFinosJournalGrantStore, task_id: TaskId) -> str:
    binding = store.get(task_id)
    assert binding is not None
    return binding.grant


def _seed_legacy(database: Path, *bindings: FinosJournalGrant) -> None:
    with sqlite3.connect(database) as connection:
        connection.execute(
            """
            CREATE TABLE finos_journal_grants (
                task_id TEXT PRIMARY KEY,
                contract_version TEXT NOT NULL,
                grant TEXT NOT NULL,
                expires_at TEXT NOT NULL
            )
            """
        )
        connection.executemany(
            "INSERT INTO finos_journal_grants VALUES (?, ?, ?, ?)",
            [
                (
                    str(binding.task_id),
                    binding.contract_version,
                    binding.grant,
                    binding.expires_at.isoformat(),
                )
                for binding in bindings
            ],
        )
