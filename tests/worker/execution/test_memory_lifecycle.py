from pathlib import Path

from agent_core.domain.events import EventType
from agent_core.domain.memories import (
    MemoryQuery,
    MemoryStatus,
    MemoryType,
)
from agent_core.domain.sessions import SessionStatus
from agent_storage import (
    SQLiteMemoryStore,
)
from worker_execution_support import (
    _agents_read_gateway,
    _assistant_only_gateway,
    _build_execution_service,
    _confirmed_memory,
    _created_at,
    _failing_tests_run_gateway,
    _procedure_refresh_gateway,
    _seed_ready_session,
    _seed_ready_session_with_input,
    _tests_run_gateway,
)


def test_worker_execution_service_persists_memory_candidate_on_success(
    tmp_path: Path,
    monkeypatch,
) -> None:
    database_path = tmp_path / "worker.db"
    (tmp_path / "Makefile").write_text("check:\n\t@echo validated\n", encoding="utf-8")
    session_id = _seed_ready_session(database_path, tmp_path)

    monkeypatch.setattr(
        "zebra_agent_worker.execution.build_model_gateway",
        lambda settings: _tests_run_gateway(settings=settings),
    )

    result = _build_execution_service(database_path).execute_session(
        session_id,
        worker_id="worker-a",
        executed_at=_created_at(),
    )

    records = SQLiteMemoryStore(database_path).list(
        MemoryQuery(
            repo_id=str(tmp_path.resolve()),
            statuses=(MemoryStatus.CANDIDATE,),
        )
    )

    assert result.session.status is SessionStatus.COMPLETED
    assert len(records) == 1
    assert records[0].memory_type is MemoryType.PROCEDURE
    assert records[0].source_session_id == session_id
    assert records[0].repo_id == str(tmp_path.resolve())
    assert any(
        event.event_type is EventType.MEMORY_CANDIDATE_EXTRACTED
        for event in result.events
    )

def test_worker_execution_service_persists_project_rule_candidate_from_agents_read(
    tmp_path: Path,
    monkeypatch,
) -> None:
    database_path = tmp_path / "worker.db"
    (tmp_path / "AGENTS.md").write_text(
        "# Zebra Agent Repository Rules\n\n"
        "## Local Commands\n\n"
        "- `make sync`\n"
        "- `make test`\n"
        "- `make check`\n",
        encoding="utf-8",
    )
    session_id = _seed_ready_session(database_path, tmp_path)

    monkeypatch.setattr(
        "zebra_agent_worker.execution.build_model_gateway",
        lambda settings: _agents_read_gateway(settings=settings),
    )

    result = _build_execution_service(database_path).execute_session(
        session_id,
        worker_id="worker-a",
        executed_at=_created_at(),
    )

    records = SQLiteMemoryStore(database_path).list(
        MemoryQuery(
            repo_id=str(tmp_path.resolve()),
            statuses=(MemoryStatus.CANDIDATE,),
        )
    )

    assert result.session.status is SessionStatus.COMPLETED
    assert any(record.memory_type is MemoryType.PROJECT_RULE for record in records)
    assert any(
        record.text == "Use the repo default commands: `make sync`, `make test`, `make check`."
        for record in records
    )
    assert any(
        event.event_type is EventType.MEMORY_CANDIDATE_EXTRACTED
        and event.payload["memory_type"] == "project_rule"
        for event in result.events
    )

def test_worker_execution_service_persists_architecture_fact_candidate_from_agents_read(
    tmp_path: Path,
    monkeypatch,
) -> None:
    database_path = tmp_path / "worker.db"
    (tmp_path / "AGENTS.md").write_text(
        "# Zebra Agent Repository Rules\n\n"
        "### packages/\n\n"
        "- packages may depend on `agent-core`\n"
        "- `agent-core` must not depend on other `agent-*` packages\n",
        encoding="utf-8",
    )
    session_id = _seed_ready_session(database_path, tmp_path)

    monkeypatch.setattr(
        "zebra_agent_worker.execution.build_model_gateway",
        lambda settings: _agents_read_gateway(settings=settings),
    )

    result = _build_execution_service(database_path).execute_session(
        session_id,
        worker_id="worker-a",
        executed_at=_created_at(),
    )

    records = SQLiteMemoryStore(database_path).list(
        MemoryQuery(
            repo_id=str(tmp_path.resolve()),
            statuses=(MemoryStatus.CANDIDATE,),
        )
    )

    assert result.session.status is SessionStatus.COMPLETED
    assert any(record.memory_type is MemoryType.ARCHITECTURE_FACT for record in records)
    assert any(
        record.text == (
            "Workspace packages may depend on `agent-core`, but `agent-core` must not "
            "depend on other `agent-*` packages."
        )
        for record in records
    )
    assert any(
        event.event_type is EventType.MEMORY_CANDIDATE_EXTRACTED
        and event.payload["memory_type"] == "architecture_fact"
        for event in result.events
    )

def test_worker_execution_service_expires_stale_confirmed_doc_memory_after_agents_refresh(
    tmp_path: Path,
    monkeypatch,
) -> None:
    database_path = tmp_path / "worker.db"
    (tmp_path / "AGENTS.md").write_text(
        "# Zebra Agent Repository Rules\n\n"
        "## Local Commands\n\n"
        "- `make sync`\n"
        "- `make check`\n",
        encoding="utf-8",
    )
    session_id = _seed_ready_session(database_path, tmp_path)
    SQLiteMemoryStore(database_path).upsert(
        _confirmed_memory(
            session_id=session_id,
            repo_id=str(tmp_path.resolve()),
            memory_type=MemoryType.PROJECT_RULE,
            text="Use the repo default commands: `make sync`, `make test`, `make check`.",
        )
    )

    monkeypatch.setattr(
        "zebra_agent_worker.execution.build_model_gateway",
        lambda settings: _agents_read_gateway(settings=settings),
    )

    result = _build_execution_service(database_path).execute_session(
        session_id,
        worker_id="worker-a",
        executed_at=_created_at(),
    )

    records = SQLiteMemoryStore(database_path).list(
        MemoryQuery(repo_id=str(tmp_path.resolve()), statuses=(MemoryStatus.EXPIRED,))
    )

    assert result.session.status is SessionStatus.COMPLETED
    assert any(record.memory_type is MemoryType.PROJECT_RULE for record in records)
    assert any(
        event.event_type is EventType.MEMORY_REVIEW_RECORDED
        and event.payload["status"] == "expired"
        and event.payload["reason"] == "stale after AGENTS.md refresh"
        for event in result.events
    )

def test_worker_execution_service_expires_stale_confirmed_procedure_after_refresh(
    tmp_path: Path,
    monkeypatch,
) -> None:
    database_path = tmp_path / "worker.db"
    (tmp_path / "Makefile").write_text("check:\n\t@echo validated\n", encoding="utf-8")
    session_id = _seed_ready_session(database_path, tmp_path)
    SQLiteMemoryStore(database_path).upsert(
        _confirmed_memory(
            session_id=session_id,
            repo_id=str(tmp_path.resolve()),
            memory_type=MemoryType.PROCEDURE,
            text="Run `make test` from `.`.",
        )
    )

    monkeypatch.setattr(
        "zebra_agent_worker.execution.build_model_gateway",
        lambda settings: _procedure_refresh_gateway(settings=settings),
    )

    result = _build_execution_service(database_path).execute_session(
        session_id,
        worker_id="worker-a",
        executed_at=_created_at(),
    )

    records = SQLiteMemoryStore(database_path).list(
        MemoryQuery(repo_id=str(tmp_path.resolve()), statuses=(MemoryStatus.EXPIRED,))
    )

    assert result.session.status is SessionStatus.COMPLETED
    assert any(record.memory_type is MemoryType.PROCEDURE for record in records)
    assert any(
        event.event_type is EventType.MEMORY_REVIEW_RECORDED
        and event.payload["status"] == "expired"
        and event.payload["reason"] == "stale after procedure refresh"
        for event in result.events
    )

def test_worker_execution_service_persists_preference_candidate_from_explicit_user_message(
    tmp_path: Path,
    monkeypatch,
) -> None:
    database_path = tmp_path / "worker.db"
    session_id = _seed_ready_session_with_input(
        database_path,
        tmp_path,
        user_input="Preference: Prefer concise CLI output.",
    )

    monkeypatch.setattr(
        "zebra_agent_worker.execution.build_model_gateway",
        lambda settings: _assistant_only_gateway(settings=settings),
    )

    result = _build_execution_service(database_path).execute_session(
        session_id,
        worker_id="worker-a",
        executed_at=_created_at(),
    )

    records = SQLiteMemoryStore(database_path).list(
        MemoryQuery(
            repo_id=str(tmp_path.resolve()),
            statuses=(MemoryStatus.CANDIDATE,),
        )
    )

    assert result.session.status is SessionStatus.COMPLETED
    assert any(record.memory_type is MemoryType.PREFERENCE for record in records)
    assert any(record.text == "Prefer concise CLI output." for record in records)
    assert any(
        event.event_type is EventType.MEMORY_CANDIDATE_EXTRACTED
        and event.payload["memory_type"] == "preference"
        for event in result.events
    )

def test_worker_execution_service_does_not_persist_memory_candidate_on_failure(
    tmp_path: Path,
    monkeypatch,
) -> None:
    database_path = tmp_path / "worker.db"
    session_id = _seed_ready_session(database_path, tmp_path)

    monkeypatch.setattr(
        "zebra_agent_worker.execution.build_model_gateway",
        lambda settings: _failing_tests_run_gateway(settings=settings),
    )

    result = _build_execution_service(database_path).execute_session(
        session_id,
        worker_id="worker-a",
        executed_at=_created_at(),
    )

    records = SQLiteMemoryStore(database_path).list(
        MemoryQuery(repo_id=str(tmp_path.resolve()), statuses=(MemoryStatus.CANDIDATE,))
    )

    assert result.session.status is SessionStatus.FAILED
    assert records == []
    assert all(
        event.event_type is not EventType.MEMORY_CANDIDATE_EXTRACTED
        for event in result.events
    )
