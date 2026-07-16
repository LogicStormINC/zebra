from pathlib import Path

import pytest
from agent_core.domain.identifiers import new_message_id
from agent_core.domain.messages import MessageRole, SessionMessage
from agent_core.domain.modeling import (
    ModelCompletion,
)
from agent_core.domain.sessions import SessionStatus
from cli_run_support import (
    FakeGateway,
    _created_at,
    _seed_active_lease,
    _seed_ready_session,
    _settings,
)
from zebra_agent_cli.cli import execute
from zebra_agent_config import ZebraAgentSettings


def test_cli_resume_command_execute_reports_missing_session(tmp_path: Path) -> None:
    database_path = tmp_path / "sessions.sqlite"

    result = execute(
        [
            "resume",
            "00000000-0000-0000-0000-000000000001",
            "--execute",
            "--database",
            str(database_path),
        ],
        settings=_settings(database_path),
    )

    assert result.payload == {
        "session_id": "00000000-0000-0000-0000-000000000001",
        "database": str(database_path),
        "status": "not_found",
    }

def test_cli_resume_command_execute_reports_not_resumable(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    database_path = tmp_path / "sessions.sqlite"
    session_id = _seed_ready_session(database_path, tmp_path)
    settings = _settings(database_path)

    def fake_build_model_gateway(active_settings: ZebraAgentSettings):
        del active_settings
        return FakeGateway(
            completion=ModelCompletion(
                assistant_message=SessionMessage(
                    message_id=new_message_id(),
                    role=MessageRole.ASSISTANT,
                    content="Resume execution complete.",
                    created_at=_created_at(),
                )
            )
        )

    monkeypatch.setattr(
        "zebra_agent_worker.execution.build_model_gateway",
        fake_build_model_gateway,
    )
    first = execute(
        [
            "resume",
            str(session_id),
            "--execute",
            "--database",
            str(database_path),
        ],
        settings=settings,
    )
    second = execute(
        [
            "resume",
            str(session_id),
            "--execute",
            "--database",
            str(database_path),
        ],
        settings=settings,
    )

    assert first.payload["status"] == SessionStatus.COMPLETED.value
    assert second.payload == {
        "session_id": str(session_id),
        "database": str(database_path),
        "status": "not_resumable",
        "reason": "cannot_resume_terminal_session",
    }

def test_cli_resume_command_execute_reports_lease_conflict(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    database_path = tmp_path / "sessions.sqlite"
    session_id = _seed_ready_session(database_path, tmp_path)
    _seed_active_lease(database_path, session_id, worker_id="worker-held")

    monkeypatch.setattr(
        "zebra_agent_worker.execution.build_model_gateway",
        lambda settings: FakeGateway(
            completion=ModelCompletion(
                assistant_message=SessionMessage(
                    message_id=new_message_id(),
                    role=MessageRole.ASSISTANT,
                    content="unused",
                    created_at=_created_at(),
                )
            )
        ),
    )

    result = execute(
        [
            "resume",
            str(session_id),
            "--execute",
            "--worker-id",
            "worker-b",
            "--database",
            str(database_path),
        ],
        settings=_settings(database_path),
    )

    assert result.payload == {
        "session_id": str(session_id),
        "database": str(database_path),
        "status": "lease_conflict",
        "reason": "session_already_leased",
    }

def test_cli_resume_command_execute_rejects_invalid_request(tmp_path: Path) -> None:
    database_path = tmp_path / "sessions.sqlite"
    session_id = _seed_ready_session(database_path, tmp_path)

    result = execute(
        [
            "resume",
            str(session_id),
            "--execute",
            "--lease-ttl-seconds",
            "0",
            "--database",
            str(database_path),
        ],
        settings=_settings(database_path),
    )

    assert result.payload == {
        "status": "invalid_request",
        "reason": "lease_ttl_seconds must be greater than zero",
        "database": str(database_path),
    }
