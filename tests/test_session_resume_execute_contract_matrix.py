from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import UUID

from agent_core.application import SessionBootstrapCommand, SessionBootstrapService
from agent_core.application.workspace_projection import rebuild_workspace
from agent_core.domain.identifiers import SessionId, new_message_id
from agent_core.domain.messages import MessageRole, SessionMessage
from agent_core.domain.modeling import (
    ModelCallMetadata,
    ModelCompletion,
    ModelToolDefinition,
    ModelUsage,
)
from agent_core.domain.sessions import SessionStatus
from agent_storage import (
    SQLiteEventStore,
    SQLiteLeaseStore,
    SQLiteProjectionStore,
    SQLiteWorkspaceProjectionStore,
)
from zebra_agent_api.app import create_app
from zebra_agent_cli.cli import execute
from zebra_agent_config import ApiSettings, ModelSettings, ZebraAgentSettings


def test_session_resume_execute_contract_matrix_success_matches_across_api_and_cli(
    tmp_path: Path,
    monkeypatch,
) -> None:
    monkeypatch.setattr(
        "zebra_agent_worker.execution.build_model_gateway",
        _fake_resume_gateway,
    )
    api_database_path = tmp_path / "api-resume.sqlite"
    api_session_id = _seed_ready_session(api_database_path, workspace_root=tmp_path)
    cli_database_path = tmp_path / "cli-resume.sqlite"
    cli_session_id = _seed_ready_session(
        cli_database_path,
        workspace_root=tmp_path,
        session_id=api_session_id,
    )

    api_response = create_app(
        api_database_path,
        settings=_settings(api_database_path),
    ).resume_session(
        api_session_id,
        {"worker_id": "worker-a", "lease_ttl_seconds": 45},
    )
    cli_result = execute(
        [
            "resume",
            cli_session_id,
            "--execute",
            "--worker-id",
            "worker-a",
            "--lease-ttl-seconds",
            "45",
            "--database",
            str(cli_database_path),
        ],
        settings=_settings(cli_database_path),
    )

    assert api_response.status_code == 200
    assert _normalize_api_resume(api_response.body) == _normalize_cli_resume(cli_result.payload)


def test_session_resume_execute_contract_matrix_missing_session_matches_across_api_and_cli(
    tmp_path: Path,
) -> None:
    database_path = tmp_path / "missing.sqlite"
    session_id = "00000000-0000-0000-0000-000000000001"

    api_response = create_app(database_path, settings=_settings(database_path)).resume_session(
        session_id,
        {},
    )
    cli_result = execute(
        [
            "resume",
            session_id,
            "--execute",
            "--database",
            str(database_path),
        ],
        settings=_settings(database_path),
    )

    assert api_response.status_code == 404
    assert _normalize_api_resume(api_response.body) == _normalize_cli_resume(cli_result.payload)


def test_session_resume_execute_contract_matrix_invalid_request_matches_across_api_and_cli(
    tmp_path: Path,
) -> None:
    database_path = tmp_path / "invalid.sqlite"
    session_id = _seed_ready_session(database_path, workspace_root=tmp_path)

    api_response = create_app(database_path, settings=_settings(database_path)).resume_session(
        session_id,
        {"lease_ttl_seconds": 0},
    )
    cli_result = execute(
        [
            "resume",
            session_id,
            "--execute",
            "--lease-ttl-seconds",
            "0",
            "--database",
            str(database_path),
        ],
        settings=_settings(database_path),
    )

    assert api_response.status_code == 400
    assert _normalize_api_resume(api_response.body) == _normalize_cli_resume(cli_result.payload)


def test_session_resume_execute_contract_matrix_lease_conflict_matches_across_api_and_cli(
    tmp_path: Path,
    monkeypatch,
) -> None:
    monkeypatch.setattr(
        "zebra_agent_worker.execution.build_model_gateway",
        _fake_resume_gateway,
    )
    api_database_path = tmp_path / "api-lease.sqlite"
    api_session_id = _seed_ready_session(api_database_path, workspace_root=tmp_path)
    _seed_active_lease(api_database_path, api_session_id, worker_id="worker-held")
    cli_database_path = tmp_path / "cli-lease.sqlite"
    cli_session_id = _seed_ready_session(
        cli_database_path,
        workspace_root=tmp_path,
        session_id=api_session_id,
    )
    _seed_active_lease(cli_database_path, cli_session_id, worker_id="worker-held")

    api_response = create_app(
        api_database_path,
        settings=_settings(api_database_path),
    ).resume_session(
        api_session_id,
        {"worker_id": "worker-b", "lease_ttl_seconds": 45},
    )
    cli_result = execute(
        [
            "resume",
            cli_session_id,
            "--execute",
            "--worker-id",
            "worker-b",
            "--lease-ttl-seconds",
            "45",
            "--database",
            str(cli_database_path),
        ],
        settings=_settings(cli_database_path),
    )

    assert api_response.status_code == 409
    assert _normalize_api_resume(api_response.body) == _normalize_cli_resume(cli_result.payload)


def test_session_resume_execute_contract_matrix_not_resumable_matches_across_api_and_cli(
    tmp_path: Path,
    monkeypatch,
) -> None:
    monkeypatch.setattr(
        "zebra_agent_worker.execution.build_model_gateway",
        _fake_resume_gateway,
    )
    api_database_path = tmp_path / "api-terminal.sqlite"
    api_session_id = _seed_ready_session(api_database_path, workspace_root=tmp_path)
    cli_database_path = tmp_path / "cli-terminal.sqlite"
    cli_session_id = _seed_ready_session(
        cli_database_path,
        workspace_root=tmp_path,
        session_id=api_session_id,
    )

    first_api_response = create_app(
        api_database_path,
        settings=_settings(api_database_path),
    ).resume_session(
        api_session_id,
        {},
    )
    first_cli_result = execute(
        [
            "resume",
            cli_session_id,
            "--execute",
            "--database",
            str(cli_database_path),
        ],
        settings=_settings(cli_database_path),
    )
    api_response = create_app(
        api_database_path,
        settings=_settings(api_database_path),
    ).resume_session(
        api_session_id,
        {},
    )
    cli_result = execute(
        [
            "resume",
            cli_session_id,
            "--execute",
            "--database",
            str(cli_database_path),
        ],
        settings=_settings(cli_database_path),
    )

    assert first_api_response.status_code == 200
    assert first_cli_result.payload["status"] == SessionStatus.COMPLETED.value
    assert api_response.status_code == 409
    assert _normalize_api_resume(api_response.body) == _normalize_cli_resume(cli_result.payload)


def _normalize_api_resume(payload: dict[str, object]) -> dict[str, object]:
    return payload


def _normalize_cli_resume(payload: dict[str, object]) -> dict[str, object]:
    return {key: value for key, value in payload.items() if key != "database"}


def _fake_resume_gateway(settings: ZebraAgentSettings):
    del settings
    return _FakeGateway(
        completion=ModelCompletion(
            assistant_message=SessionMessage(
                message_id=new_message_id(),
                role=MessageRole.ASSISTANT,
                content="Resume execution complete.",
                created_at=_created_at(),
            ),
            call_metadata=ModelCallMetadata(
                provider="test",
                model_name="test-model",
                latency_ms=5,
                usage=ModelUsage(total_tokens=6),
            ),
        )
    )


class _FakeGateway:
    def __init__(self, *, completion: ModelCompletion) -> None:
        self._completion = completion

    def complete(
        self,
        messages: list[SessionMessage],
        *,
        tools: tuple[ModelToolDefinition, ...] = (),
    ) -> ModelCompletion:
        assert tools
        assert len(messages) in {1, 2}
        assert messages[-1].role is MessageRole.USER
        return self._completion


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


def _seed_ready_session(
    database_path: Path,
    *,
    workspace_root: Path,
    session_id: str | None = None,
) -> str:
    bootstrap = SessionBootstrapService().build(
        SessionBootstrapCommand(
            title="Resume execute contract",
            user_input="Continue the queued session.",
            workspace_root=workspace_root.resolve(),
        )
    )
    session = bootstrap.session
    events = bootstrap.events
    if session_id is not None:
        stable_session_id = SessionId(UUID(session_id))
        session = session.model_copy(update={"session_id": stable_session_id})
        events = tuple(
            event.model_copy(update={"session_id": session.session_id})
            for event in bootstrap.events
        )

    event_store = SQLiteEventStore(database_path)
    for event in events:
        event_store.append(event)
    SQLiteProjectionStore(database_path).save_session(session)
    SQLiteWorkspaceProjectionStore(database_path).save_workspace(rebuild_workspace(list(events)))
    return str(session.session_id)


def _seed_active_lease(database_path: Path, session_id: str, *, worker_id: str) -> None:
    SQLiteLeaseStore(database_path).acquire(
        SessionId(UUID(session_id)),
        owner_instance_id=worker_id,
        ttl=timedelta(minutes=1),
    )


def _created_at() -> datetime:
    return datetime(2026, 7, 2, 12, 0, tzinfo=UTC)
