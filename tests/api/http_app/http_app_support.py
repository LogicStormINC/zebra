from datetime import UTC, datetime
from pathlib import Path

from agent_core.application import SessionBootstrapCommand, SessionBootstrapService
from agent_core.application.mock_model import ScriptedModelGateway, ScriptedModelResponse
from agent_core.domain.identifiers import new_message_id
from agent_core.domain.messages import MessageRole, SessionMessage
from agent_core.domain.modeling import ModelCompletion
from agent_storage import SQLiteEventStore, SQLiteProjectionStore
from zebra_agent_config import ApiSettings, ModelSettings, ZebraAgentSettings


def _settings(auth_token: str | None) -> ZebraAgentSettings:
    return ZebraAgentSettings(
        profile="test",
        database_url=":memory:",
        api=ApiSettings(auth_token=auth_token),
        model=ModelSettings(
            provider="test",
            api_key_env="TEST_API_KEY",
            base_url="https://example.test",
            model="test-model",
        ),
    )

def _created_at():
    from datetime import UTC, datetime

    return datetime(2026, 6, 22, 13, 25, tzinfo=UTC)

def _seed_ready_session(database_path: Path, *, workspace_root: Path) -> str:
    bootstrap = SessionBootstrapService().build(
        SessionBootstrapCommand(
            title="HTTP queued session",
            user_input="Summarize the workspace",
            workspace_root=workspace_root,
        )
    )
    event_store = SQLiteEventStore(database_path)
    for event in bootstrap.events:
        event_store.append(event)
    SQLiteProjectionStore(database_path).save_session(bootstrap.session)
    return str(bootstrap.session.session_id)

def _fake_resume_gateway(_settings: ZebraAgentSettings) -> ScriptedModelGateway:
    return ScriptedModelGateway(
        responses=(
            ScriptedModelResponse(
                completion=ModelCompletion(
                    assistant_message=SessionMessage(
                        message_id=new_message_id(),
                        role=MessageRole.ASSISTANT,
                        content="HTTP resume complete.",
                        created_at=datetime(2026, 6, 22, 13, 25, tzinfo=UTC),
                    )
                )
            ),
        )
    )
