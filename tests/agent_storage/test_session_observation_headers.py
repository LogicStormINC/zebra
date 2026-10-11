"""All Session writers derive bounded headers; legacy repair is explicit."""

import json
import sqlite3
from contextlib import contextmanager
from pathlib import Path
from uuid import UUID, uuid4

import pytest
from agent_core.domain.identifiers import TaskId
from agent_storage import SQLiteAgentTaskStore, SQLiteProjectionStore
from agent_storage.session_observation_headers import prepare_session_observation_headers


def connection(path: Path) -> sqlite3.Connection:
    database = sqlite3.connect(path)
    database.row_factory = sqlite3.Row
    return database


def insert(database: sqlite3.Connection, identity: str, *, title: str = "Header") -> None:
    database.execute(
        "INSERT INTO session_projections "
        "(session_id,title,status,created_at,updated_at,current_sequence) "
        "VALUES (?,?,'ready','2026-10-03','2026-10-03',7)",
        (identity, title),
    )


def test_raw_handoff_import_and_updates_share_atomic_derived_headers(tmp_path: Path) -> None:
    path = tmp_path / "atomic.sqlite"
    SQLiteProjectionStore(path)
    identity = str(uuid4())
    with connection(path) as database:
        # Raw writes exercise the same path used by Handoff/import, not just save_session.
        insert(database, identity, title="图" * 800)
        row = database.execute("SELECT * FROM session_observation_headers").fetchone()
        assert row["title"] == "图" * 512 and row["title_truncated"] == 1
        assert row["current_sequence"] == 7 and row["deployment_namespace"] == ""
        database.commit()
        database.execute(
            "UPDATE session_projections SET title='New',current_sequence=8 WHERE session_id=?",
            (identity,),
        )
        assert (
            database.execute("SELECT title FROM session_observation_headers").fetchone()[0] == "New"
        )
        database.rollback()
        assert (
            database.execute("SELECT title FROM session_observation_headers").fetchone()[0]
            == "图" * 512
        )
        database.execute("DELETE FROM session_projections WHERE session_id=?", (identity,))
        assert (
            database.execute("SELECT COUNT(*) FROM session_observation_headers").fetchone()[0] == 0
        )
        database.rollback()
        assert (
            database.execute("SELECT COUNT(*) FROM session_observation_headers").fetchone()[0] == 1
        )


@pytest.mark.parametrize(
    "context,expected,invalid",
    [
        (None, None, 0),
        (json.dumps({"clarification_id": "valid-id", "question": "x" * 100_000}), "valid-id", 0),
        ("not json", None, 1),
        ("{}", None, 1),
        ("[]", None, 1),
        (json.dumps({"clarification_id": True}), None, 1),
        (json.dumps({"clarification_id": 42}), None, 1),
        (json.dumps({"clarification_id": " "}), None, 1),
        (json.dumps({"clarification_id": "x" * 257}), None, 1),
        (json.dumps({"clarification_id": "bad\nidentity"}), None, 1),
        (json.dumps({"clarification_id": "bad\u0000identity"}), None, 1),
    ],
)
def test_clarification_shape_is_derived_without_legacy_json_errors(
    tmp_path: Path, context: str | None, expected: str | None, invalid: int
) -> None:
    path = tmp_path / "clarification.sqlite"
    SQLiteProjectionStore(path)
    with connection(path) as database:
        identity = str(uuid4())
        insert(database, identity)
        database.execute(
            "UPDATE session_projections SET clarification_context_json=? WHERE session_id=?",
            (context, identity),
        )
        row = database.execute(
            "SELECT clarification_id,clarification_invalid FROM session_observation_headers"
        ).fetchone()
        assert tuple(row) == (expected, invalid)


def test_legacy_preparation_is_paged_transactional_and_resumes_after_reopen(tmp_path: Path) -> None:
    path = tmp_path / "legacy.sqlite"
    SQLiteProjectionStore(path)
    with connection(path) as database:
        for number in range(600):
            insert(database, str(uuid4()), title=str(number))
        database.execute("DELETE FROM session_observation_headers")
        database.commit()
        first = prepare_session_observation_headers(database)
        assert len(first) == 256 and first == tuple(sorted(first))
        database.rollback()
        assert (
            database.execute("SELECT COUNT(*) FROM session_observation_headers").fetchone()[0] == 0
        )
        first = prepare_session_observation_headers(database)
        database.commit()
    with connection(path) as recovered:
        second = prepare_session_observation_headers(recovered, after_session_id=first[-1])
        third = prepare_session_observation_headers(recovered, after_session_id=second[-1])
        assert (len(first), len(second), len(third)) == (256, 256, 88)
        assert not set(first).intersection(second) and not set(second).intersection(third)
        assert prepare_session_observation_headers(recovered, after_session_id=third[-1]) == ()
        assert (
            recovered.execute("SELECT COUNT(*) FROM session_observation_headers").fetchone()[0]
            == 600
        )


@pytest.mark.parametrize("limit", [True, 0, 257, -1, 1.5])
def test_preparation_rejects_unbounded_pages(tmp_path: Path, limit: object) -> None:
    path = tmp_path / "bounds.sqlite"
    SQLiteProjectionStore(path)
    with connection(path) as database, pytest.raises(ValueError, match="bounded page"):
        prepare_session_observation_headers(database, limit=limit)


def test_task_header_reads_no_projection_bodies_even_when_they_are_large(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    path = tmp_path / "body-free.sqlite"
    store = SQLiteAgentTaskStore(path)
    identity = str(uuid4())
    with connection(path) as database:
        insert(database, identity)
        database.execute(
            "UPDATE session_projections SET task_plan_json=?,approval_context_json=?",
            (json.dumps({"large": "x" * 8_000_000}), json.dumps({"large": "y" * 8_000_000})),
        )
        database.execute(
            "INSERT INTO agent_tasks (task_id,root_session_id,active_segment_id,"
            "created_at,updated_at,next_event_sequence,event_position_state) "
            "VALUES (?,?,?,'2026-10-03','2026-10-03',10,'ready')",
            (identity, identity, identity),
        )
    original = store._database.connect

    @contextmanager
    def scalar_only():
        with original() as database:
            database.set_authorizer(
                lambda action, table, _column, _database, _trigger: sqlite3.SQLITE_DENY
                if action == sqlite3.SQLITE_READ
                and table in {"session_projections", "session_events", "execution_segments"}
                else sqlite3.SQLITE_OK
            )
            yield database

    monkeypatch.setattr(store._database, "connect", scalar_only)
    header = store.read_task_header(TaskId(uuid4()))
    assert header is None
    header = store.read_task_header(TaskId(UUID(identity)))
    assert header is not None and header.title == "Header" and header.current_sequence == 9
    with connection(path) as database:
        database.execute("DELETE FROM session_observation_headers")
    header = store.read_task_header(TaskId(UUID(identity)))
    assert header is not None and header.title is None and header.status is None
    with connection(path) as database:
        assert (
            database.execute("SELECT COUNT(*) FROM session_observation_headers").fetchone()[0] == 0
        )
