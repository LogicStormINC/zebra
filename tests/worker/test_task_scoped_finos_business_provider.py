from __future__ import annotations

import sqlite3
from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import UUID

from agent_core.domain.identifiers import TaskId
from agent_storage import FinosJournalGrant, SQLiteAgentTaskStore, SQLiteFinosJournalGrantStore
from zebra_agent_api import RouteAdapter, RouteRequest, create_app
from zebra_agent_config import (
    ApiSettings,
    FinosJournalProviderSettings,
    ModelSettings,
    ZebraAgentSettings,
)
from zebra_agent_worker.finos_journal_provider import build_finos_journal_provider


def test_worker_builds_provider_only_for_active_task_binding(tmp_path: Path) -> None:
    database, task_id = _task(database=tmp_path / "tasks.sqlite", workspace=tmp_path)
    task = SQLiteAgentTaskStore(database).get_task(task_id)
    assert task is not None
    SQLiteFinosJournalGrantStore(database).bind(
        FinosJournalGrant(
            task_id=task_id,
            contract_version="finos.journals.v1",
            grant="active-private-grant",
            expires_at=datetime.now(UTC) + timedelta(hours=1),
        )
    )

    provider = build_finos_journal_provider(
        settings=_settings(database, base_url="https://finos.internal"),
        database_path=database,
        session_id=task.active_segment_id,
    )

    assert provider is not None
    assert provider.task_id == str(task_id)
    assert "active-private-grant" not in repr(provider)


def test_worker_fails_closed_for_expired_or_missing_task_binding(tmp_path: Path) -> None:
    database, task_id = _task(database=tmp_path / "tasks.sqlite", workspace=tmp_path)
    task = SQLiteAgentTaskStore(database).get_task(task_id)
    assert task is not None
    settings = _settings(database, base_url="https://finos.internal")
    assert build_finos_journal_provider(
        settings=settings, database_path=database, session_id=task.active_segment_id
    ) is None
    SQLiteFinosJournalGrantStore(database).bind(
        FinosJournalGrant(
            task_id=task_id,
            contract_version="finos.journals.v1",
            grant="expired-private-grant",
            expires_at=datetime.now(UTC) - timedelta(seconds=1),
        )
    )

    assert build_finos_journal_provider(
        settings=settings, database_path=database, session_id=task.active_segment_id
    ) is None


def test_worker_resolves_a_continuation_to_the_original_stable_task_binding(tmp_path: Path) -> None:
    database, task_id = _task(database=tmp_path / "tasks.sqlite", workspace=tmp_path)
    adapter = RouteAdapter(create_app(database))
    SQLiteFinosJournalGrantStore(database).bind(
        FinosJournalGrant(
            task_id=task_id,
            contract_version="finos.journals.v1",
            grant="active-private-grant",
            expires_at=datetime.now(UTC) + timedelta(hours=1),
        )
    )
    cancelled = adapter.handle(RouteRequest("POST", f"/tasks/{task_id}/cancel", body={}))
    assert cancelled.status_code == 200
    continued = adapter.handle(
        RouteRequest("POST", f"/tasks/{task_id}/messages", body={"content": "Continue"})
    )
    task = SQLiteAgentTaskStore(database).get_task(task_id)
    assert task is not None

    provider = build_finos_journal_provider(
        settings=_settings(database, base_url="https://finos.internal"),
        database_path=database,
        session_id=task.active_segment_id,
    )

    assert continued.status_code == 201
    assert provider is not None
    assert provider.task_id == str(task_id)


def test_worker_fails_closed_for_conflicting_legacy_task_bindings(tmp_path: Path) -> None:
    database, first_task_id = _task(database=tmp_path / "tasks.sqlite", workspace=tmp_path)
    _, second_task_id = _task(database=database, workspace=tmp_path / "second")
    expiry = datetime.now(UTC) + timedelta(hours=1)
    SQLiteFinosJournalGrantStore(database).bind(
        FinosJournalGrant(
            task_id=first_task_id,
            contract_version="finos.journals.v1",
            grant="shared-legacy-grant",
            expires_at=expiry,
        )
    )
    with sqlite3.connect(database) as connection:
        connection.execute(
            "INSERT INTO finos_journal_grants VALUES (?, ?, ?, ?)",
            (
                str(second_task_id),
                "finos.journals.v1",
                "shared-legacy-grant",
                expiry.isoformat(),
            ),
        )
    task_store = SQLiteAgentTaskStore(database)
    first_task = task_store.get_task(first_task_id)
    second_task = task_store.get_task(second_task_id)
    assert first_task is not None
    assert second_task is not None
    settings = _settings(database, base_url="https://finos.internal")

    assert build_finos_journal_provider(
        settings=settings,
        database_path=database,
        session_id=first_task.active_segment_id,
    ) is None
    assert build_finos_journal_provider(
        settings=settings,
        database_path=database,
        session_id=second_task.active_segment_id,
    ) is None


def _task(*, database: Path, workspace: Path) -> tuple[Path, TaskId]:
    adapter = RouteAdapter(create_app(database))
    created = adapter.handle(
        RouteRequest("POST", "/tasks", body={"prompt": "Review", "workspace": str(workspace)})
    )
    return database, TaskId(UUID(created.body["task_id"]))


def _settings(database: Path, *, base_url: str | None) -> ZebraAgentSettings:
    return ZebraAgentSettings(
        profile="test",
        database_url=str(database),
        api=ApiSettings(auth_token=None),
        model=ModelSettings(
            provider="test",
            api_key_env="TEST_API_KEY",
            base_url="https://example.test",
            model="test-model",
        ),
        finos_journal_provider=FinosJournalProviderSettings(base_url=base_url),
    )
