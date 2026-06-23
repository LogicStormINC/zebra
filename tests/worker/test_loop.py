from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

from agent_core.application import SessionBootstrapCommand, SessionBootstrapService
from agent_core.application.mock_model import ScriptedModelGateway, ScriptedModelResponse
from agent_core.domain.identifiers import SessionId, new_message_id
from agent_core.domain.messages import MessageRole, SessionMessage
from agent_core.domain.modeling import ModelCallMetadata, ModelCompletion, ModelUsage
from agent_core.domain.sessions import SessionStatus
from agent_storage import SQLiteEventStore, SQLiteLeaseStore, SQLiteProjectionStore
from pytest import CaptureFixture, MonkeyPatch
from zebra_agent_config import ApiSettings, ModelSettings, ZebraAgentSettings
from zebra_agent_worker import build_worker_loop_service
from zebra_agent_worker.main import main


def test_worker_loop_returns_idle_when_no_ready_sessions(tmp_path: Path) -> None:
    result = build_worker_loop_service(
        database_path=tmp_path / "worker.db",
        settings=_settings(tmp_path / "worker.db"),
        sleep=lambda _: None,
    ).run(
        worker_id="worker-a",
        max_cycles=1,
        stop_when_idle=True,
    )

    assert result.cycles_completed == 1
    assert result.idle_cycles == 1
    assert result.stop_reason == "idle"
    assert result.executed_session_ids == ()


def test_worker_loop_polls_multiple_idle_cycles_without_final_sleep(
    tmp_path: Path,
) -> None:
    sleep_calls: list[float] = []

    result = build_worker_loop_service(
        database_path=tmp_path / "worker.db",
        settings=_settings(tmp_path / "worker.db"),
        sleep=sleep_calls.append,
    ).run(
        worker_id="worker-a",
        max_cycles=3,
        stop_when_idle=False,
        idle_sleep_seconds=0.25,
    )

    assert result.cycles_completed == 3
    assert result.idle_cycles == 3
    assert result.stop_reason == "max_cycles"
    assert sleep_calls == [0.25, 0.25]


def test_worker_loop_executes_ready_session(
    tmp_path: Path,
    monkeypatch: MonkeyPatch,
) -> None:
    database_path = tmp_path / "worker.db"
    session_id = _seed_ready_session(database_path, tmp_path)
    monkeypatch.setattr(
        "zebra_agent_worker.execution.build_model_gateway",
        lambda settings: _assistant_only_gateway(settings=settings),
    )

    result = build_worker_loop_service(
        database_path=database_path,
        settings=_settings(database_path),
        sleep=lambda _: None,
    ).run(
        worker_id="worker-a",
        max_cycles=1,
        stop_when_idle=True,
    )

    session = SQLiteProjectionStore(database_path).get_session(session_id)
    assert result.executed_session_ids == (str(session_id),)
    assert session is not None
    assert session.status is SessionStatus.COMPLETED


def test_worker_loop_processes_multiple_ready_sessions_until_idle(
    tmp_path: Path,
    monkeypatch: MonkeyPatch,
) -> None:
    database_path = tmp_path / "worker.db"
    first = _seed_ready_session(database_path, tmp_path)
    second = _seed_ready_session(database_path, tmp_path)
    monkeypatch.setattr(
        "zebra_agent_worker.execution.build_model_gateway",
        lambda settings: _assistant_only_gateway(settings=settings),
    )

    result = build_worker_loop_service(
        database_path=database_path,
        settings=_settings(database_path),
        sleep=lambda _: None,
    ).run(
        worker_id="worker-a",
        batch_size=1,
        max_cycles=3,
        stop_when_idle=True,
    )

    assert result.cycles_completed == 3
    assert result.idle_cycles == 1
    assert result.stop_reason == "idle"
    assert result.executed_session_ids == (str(first), str(second))


def test_worker_loop_skips_already_leased_ready_session(
    tmp_path: Path,
    monkeypatch: MonkeyPatch,
) -> None:
    database_path = tmp_path / "worker.db"
    session_id = _seed_ready_session(database_path, tmp_path)
    monkeypatch.setattr(
        "zebra_agent_worker.execution.build_model_gateway",
        lambda settings: _assistant_only_gateway(settings=settings),
    )
    lease_store = SQLiteLeaseStore(database_path)
    lease_store.acquire(
        session_id,
        worker_id="worker-held",
        acquired_at=_created_at(),
        expires_at=_created_at().replace(minute=1),
    )

    result = build_worker_loop_service(
        database_path=database_path,
        settings=_settings(database_path),
        sleep=lambda _: None,
    ).run(
        worker_id="worker-b",
        max_cycles=1,
        stop_when_idle=True,
    )

    session = SQLiteProjectionStore(database_path).get_session(session_id)
    assert result.executed_session_ids == ()
    assert result.skipped_session_ids == (str(session_id),)
    assert result.stop_reason == "blocked"
    assert session is not None
    assert session.status is SessionStatus.READY


def test_worker_main_emits_loop_summary(
    tmp_path: Path,
    monkeypatch: MonkeyPatch,
    capsys: CaptureFixture[str],
) -> None:
    database_path = tmp_path / "worker.db"
    session_id = _seed_ready_session(database_path, tmp_path)
    monkeypatch.setattr(
        "zebra_agent_worker.execution.build_model_gateway",
        lambda settings: _assistant_only_gateway(settings=settings),
    )
    monkeypatch.setattr(
        "zebra_agent_worker.main.load_settings",
        lambda: _settings(database_path),
    )

    exit_code = main(
        [
            "--database",
            str(database_path),
            "--worker-id",
            "worker-a",
            "--max-cycles",
            "1",
            "--stop-when-idle",
        ]
    )

    payload = json.loads(capsys.readouterr().out)
    assert exit_code == 0
    assert payload["command"] == "loop"
    assert payload["executed_session_ids"] == [str(session_id)]
    assert payload["worker_id"] == "worker-a"
    assert payload["stop_reason"] == "max_cycles"


def test_worker_loop_rejects_invalid_loop_inputs(tmp_path: Path) -> None:
    service = build_worker_loop_service(
        database_path=tmp_path / "worker.db",
        settings=_settings(tmp_path / "worker.db"),
        sleep=lambda _: None,
    )

    try:
        service.run(worker_id="worker-a", max_cycles=0)
    except ValueError as error:
        assert str(error) == "max_cycles must be greater than zero when provided"
    else:
        raise AssertionError("expected invalid max_cycles to fail")


def _seed_ready_session(database_path: Path, workspace_root: Path) -> SessionId:
    bootstrap = SessionBootstrapService().build(
        SessionBootstrapCommand(
            title="Queued worker task",
            user_input="Continue the queued task.",
            workspace_root=workspace_root.resolve(),
        )
    )
    event_store = SQLiteEventStore(database_path)
    for event in bootstrap.events:
        event_store.append(event)
    SQLiteProjectionStore(database_path).save_session(bootstrap.session)
    return bootstrap.session.session_id


def _settings(database_path: Path) -> ZebraAgentSettings:
    return ZebraAgentSettings(
        profile="test",
        database_url=str(database_path),
        api=ApiSettings(auth_token=None),
        model=ModelSettings(
            provider="test",
            api_key_env="TEST_API_KEY",
            base_url="https://example.test",
            model="test-model",
        ),
    )


def _assistant_only_gateway(*, settings: ZebraAgentSettings) -> ScriptedModelGateway:
    del settings
    return ScriptedModelGateway(
        responses=(
            ScriptedModelResponse(
                completion=ModelCompletion(
                    assistant_message=SessionMessage(
                        message_id=new_message_id(),
                        role=MessageRole.ASSISTANT,
                        content="Worker completed the session.",
                        created_at=_created_at(),
                    ),
                    call_metadata=ModelCallMetadata(
                        provider="test",
                        model_name="test-model",
                        usage=ModelUsage(total_tokens=7),
                    ),
                )
            ),
        )
    )


def _created_at() -> datetime:
    return datetime(2026, 6, 23, 9, 0, tzinfo=UTC)
