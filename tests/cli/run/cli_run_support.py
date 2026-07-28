from datetime import UTC, datetime, timedelta
from pathlib import Path

from agent_core.domain.identifiers import SessionId, new_message_id
from agent_core.domain.messages import MessageRole, SessionMessage
from agent_core.domain.modeling import (
    ModelCompletion,
    ModelToolDefinition,
)
from agent_storage import (
    SQLiteEventStore,
    SQLiteLeaseStore,
    SQLiteProjectionStore,
)
from zebra_agent_config import ApiSettings, McpServerSettings, ModelSettings, ZebraAgentSettings


def _settings(
    database_path: Path,
    *,
    mcp_servers: tuple[McpServerSettings, ...] = (),
) -> ZebraAgentSettings:
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
        mcp_servers=mcp_servers,
    )

def _created_at() -> datetime:
    return datetime(2026, 6, 22, 12, 30, tzinfo=UTC)

class FakeGateway:
    def __init__(self, *, completion: ModelCompletion) -> None:
        self._completion = completion

    def complete(
        self,
        messages: list[SessionMessage],
        *,
        tools: tuple[ModelToolDefinition, ...] = (),
    ) -> ModelCompletion:
        tool_message = next(
            (message for message in messages if message.role is MessageRole.TOOL),
            None,
        )
        if tool_message is not None:
            return ModelCompletion(
                assistant_message=SessionMessage(
                    message_id=new_message_id(),
                    role=MessageRole.ASSISTANT,
                    content=f"Tool result: {tool_message.content}",
                    created_at=_created_at(),
                )
            )
        assert len(messages) in {1, 2}
        assert messages[-1].role is MessageRole.USER
        return self._completion

def _seed_ready_session(database_path: Path, workspace_root: Path) -> SessionId:
    from agent_core.application import SessionBootstrapCommand, SessionBootstrapService

    bootstrap = SessionBootstrapService().build(
        SessionBootstrapCommand(
            title="Resume task",
            user_input="Continue the queued session.",
            workspace_root=workspace_root.resolve(),
        )
    )
    event_store = SQLiteEventStore(database_path)
    for event in bootstrap.events:
        event_store.append(event)
    SQLiteProjectionStore(database_path).save_session(bootstrap.session)
    return bootstrap.session.session_id

def _seed_active_lease(database_path: Path, session_id: SessionId, *, worker_id: str) -> None:
    SQLiteLeaseStore(database_path).acquire(
        session_id,
        owner_instance_id=worker_id,
        ttl=timedelta(minutes=1),
    )
