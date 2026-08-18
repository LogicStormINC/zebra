"""Worker-level coverage for workspace:// runtime resolution."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from uuid import UUID

import pytest
from agent_core.application import SessionBootstrapCommand, SessionBootstrapService
from agent_core.application.mock_model import ScriptedModelGateway, ScriptedModelResponse
from agent_core.domain.identifiers import new_message_id
from agent_core.domain.messages import MessageRole, SessionMessage
from agent_core.domain.modeling import ModelCompletion
from agent_core.domain.sessions import SessionStatus
from agent_storage import (
    SQLiteEventStore,
    SQLiteLeaseStore,
    SQLiteProjectionStore,
    SQLiteWorkspaceProjectionStore,
)
from zebra_agent_config import ApiSettings, ModelSettings, ZebraAgentSettings
from zebra_agent_worker import (
    SessionClaimService,
    SessionExecutionService,
    SessionRecoveryService,
    SessionResumeService,
)


class RecordingResolver:
    def __init__(self, resolved_root: Path) -> None:
        self.resolved_root = resolved_root
        self.references: list[str] = []

    def resolve(self, workspace_ref: str, *, session_id: UUID) -> Path:
        self.references.append(workspace_ref)
        return self.resolved_root


def test_execution_resolves_workspace_uri_before_runtime(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    database_path = tmp_path / "resolver.sqlite"
    bootstrap = SessionBootstrapService().build(
        SessionBootstrapCommand(
            title="Resolved workspace",
            user_input="run inside the control-plane workspace",
            workspace_root=Path("workspace://00000000-0000-0000-0000-000000000001"),
            policy_profile="workspace_write",
            network_profile="none",
        )
    )
    event_store = SQLiteEventStore(database_path)
    for event in bootstrap.events:
        event_store.append(event)
    SQLiteProjectionStore(database_path).save_session(bootstrap.session)
    SessionRecoveryService(
        event_store,
        SQLiteProjectionStore(database_path),
        SQLiteWorkspaceProjectionStore(database_path),
    ).recover_session(bootstrap.session.session_id)

    gateway = ScriptedModelGateway(
        responses=(
            ScriptedModelResponse(
                completion=ModelCompletion(
                    assistant_message=SessionMessage(
                        message_id=new_message_id(),
                        role=MessageRole.ASSISTANT,
                        content="resolved",
                        created_at=datetime(2026, 8, 16, 0, 0, tzinfo=UTC),
                    ),
                )
            ),
        )
    )
    monkeypatch.setattr(
        "zebra_agent_worker.execution.build_model_gateway",
        lambda settings: gateway,
    )
    materialized = tmp_path / "materialized"
    materialized.mkdir()
    (materialized / "README.md").write_text("provisioned\n")
    resolver = RecordingResolver(materialized)

    claim_service = SessionClaimService(
        SQLiteLeaseStore(database_path),
        SessionRecoveryService(
            SQLiteEventStore(database_path),
            SQLiteProjectionStore(database_path),
            SQLiteWorkspaceProjectionStore(database_path),
        ),
    )
    service = SessionExecutionService(
        database_path=database_path,
        claim_service=claim_service,
        resume_service=SessionResumeService(claim_service),
        settings=_settings(database_path),
        workspace_resolver=resolver,  # type: ignore[arg-type]
    )

    executed = service.execute_session(
        bootstrap.session.session_id,
        worker_id="resolver-worker",
        executed_at=datetime(2026, 8, 16, 0, 0, tzinfo=UTC),
    )

    assert executed.session.status is SessionStatus.COMPLETED
    assert len(resolver.references) == 1
    assert resolver.references[0].endswith("00000000-0000-0000-0000-000000000001")


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
