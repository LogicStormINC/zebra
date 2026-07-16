from datetime import UTC, datetime
from pathlib import Path
from uuid import UUID

from agent_core.application import SessionBootstrapCommand, SessionBootstrapService
from agent_core.application.mock_model import ScriptedModelGateway, ScriptedModelResponse
from agent_core.domain.identifiers import MemoryId, SessionId, new_message_id, new_tool_call_id
from agent_core.domain.memories import (
    MemoryRecord,
    MemoryStatus,
    MemoryType,
    MemoryVisibility,
)
from agent_core.domain.messages import MessageRole, SessionMessage
from agent_core.domain.modeling import ModelCallMetadata, ModelCompletion, ModelUsage
from agent_core.domain.tool_profiles import ToolProfile
from agent_core.domain.tools import ToolCall
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


def _build_execution_service(database_path: Path) -> SessionExecutionService:
    claim_service = SessionClaimService(
        SQLiteLeaseStore(database_path),
        SessionRecoveryService(
            SQLiteEventStore(database_path),
            SQLiteProjectionStore(database_path),
            SQLiteWorkspaceProjectionStore(database_path),
        ),
    )
    return SessionExecutionService(
        database_path=database_path,
        claim_service=claim_service,
        resume_service=SessionResumeService(claim_service),
        settings=_settings(database_path),
    )

def _seed_ready_session(database_path: Path, workspace_root: Path) -> SessionId:
    return _seed_ready_session_with_input(
        database_path,
        workspace_root,
        user_input="Continue the queued task.",
    )

def _seed_ready_session_with_input(
    database_path: Path,
    workspace_root: Path,
    *,
    user_input: str,
    network_profile: str = "none",
    network_allowlist: tuple[str, ...] = (),
) -> SessionId:
    bootstrap = SessionBootstrapService().build(
        SessionBootstrapCommand(
            title="Queued worker task",
            user_input=user_input,
            workspace_root=workspace_root.resolve(),
            tool_profile=ToolProfile.CODING,
            network_profile=network_profile,
            network_allowlist=network_allowlist,
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

def _final_response(content: str) -> ScriptedModelResponse:
    return ScriptedModelResponse(
        completion=ModelCompletion(
            assistant_message=SessionMessage(
                message_id=new_message_id(),
                role=MessageRole.ASSISTANT,
                content=content,
                created_at=_created_at(),
            )
        )
    )

def _tool_gateway(*, settings: ZebraAgentSettings) -> ScriptedModelGateway:
    del settings
    return ScriptedModelGateway(
        responses=(
            ScriptedModelResponse(
                completion=ModelCompletion(
                    assistant_message=SessionMessage(
                        message_id=new_message_id(),
                        role=MessageRole.ASSISTANT,
                        content="Reading README.",
                        created_at=_created_at(),
                    ),
                    tool_calls=(
                        ToolCall(
                            tool_call_id=new_tool_call_id(),
                            name="files.read",
                            arguments={"path": "README.md"},
                            created_at=_created_at(),
                        ),
                    ),
                    call_metadata=ModelCallMetadata(
                        provider="test",
                        model_name="test-model",
                        usage=ModelUsage(total_tokens=9),
                    ),
                )
            ),
            _final_response("README content returned."),
        )
    )

def _agents_read_gateway(*, settings: ZebraAgentSettings) -> ScriptedModelGateway:
    del settings
    return ScriptedModelGateway(
        responses=(
            ScriptedModelResponse(
                completion=ModelCompletion(
                    assistant_message=SessionMessage(
                        message_id=new_message_id(),
                        role=MessageRole.ASSISTANT,
                        content="Reading AGENTS.",
                        created_at=_created_at(),
                    ),
                    tool_calls=(
                        ToolCall(
                            tool_call_id=new_tool_call_id(),
                            name="files.read",
                            arguments={"path": "AGENTS.md"},
                            created_at=_created_at(),
                        ),
                    ),
                    call_metadata=ModelCallMetadata(
                        provider="test",
                        model_name="test-model",
                        usage=ModelUsage(total_tokens=9),
                    ),
                )
            ),
            _final_response("AGENTS instructions returned."),
        )
    )

def _tests_run_gateway(*, settings: ZebraAgentSettings) -> ScriptedModelGateway:
    del settings
    return ScriptedModelGateway(
        responses=(
            ScriptedModelResponse(
                completion=ModelCompletion(
                    assistant_message=SessionMessage(
                        message_id=new_message_id(),
                        role=MessageRole.ASSISTANT,
                        content="Run smoke validation.",
                        created_at=_created_at(),
                    ),
                    tool_calls=(
                        ToolCall(
                            tool_call_id=new_tool_call_id(),
                            name="tests.run",
                            arguments={"preset": "check"},
                            created_at=_created_at(),
                        ),
                    ),
                    call_metadata=ModelCallMetadata(
                        provider="test",
                        model_name="test-model",
                        usage=ModelUsage(total_tokens=9),
                    ),
                )
            ),
            _final_response("Smoke validation completed."),
        )
    )

def _procedure_refresh_gateway(*, settings: ZebraAgentSettings) -> ScriptedModelGateway:
    del settings
    return ScriptedModelGateway(
        responses=(
            ScriptedModelResponse(
                completion=ModelCompletion(
                    assistant_message=SessionMessage(
                        message_id=new_message_id(),
                        role=MessageRole.ASSISTANT,
                        content="Refresh repo procedure.",
                        created_at=_created_at(),
                    ),
                    tool_calls=(
                        ToolCall(
                            tool_call_id=new_tool_call_id(),
                            name="tests.run",
                            arguments={"preset": "check"},
                            created_at=_created_at(),
                        ),
                    ),
                    call_metadata=ModelCallMetadata(
                        provider="test",
                        model_name="test-model",
                        usage=ModelUsage(total_tokens=9),
                    ),
                )
            ),
            _final_response("Repository procedure refreshed."),
        )
    )

def _failing_tests_run_gateway(*, settings: ZebraAgentSettings) -> ScriptedModelGateway:
    del settings
    return ScriptedModelGateway(
        responses=(
            ScriptedModelResponse(
                completion=ModelCompletion(
                    assistant_message=SessionMessage(
                        message_id=new_message_id(),
                        role=MessageRole.ASSISTANT,
                        content="Run failing smoke validation.",
                        created_at=_created_at(),
                    ),
                    tool_calls=(
                        ToolCall(
                            tool_call_id=new_tool_call_id(),
                            name="tests.run",
                            arguments={"preset": "failing"},
                            created_at=_created_at(),
                        ),
                    ),
                    call_metadata=ModelCallMetadata(
                        provider="test",
                        model_name="test-model",
                        usage=ModelUsage(total_tokens=9),
                    ),
                )
            ),
            _final_response("Smoke validation failed."),
        )
    )

def _created_at() -> datetime:
    return datetime(2026, 6, 22, 14, 0, tzinfo=UTC)

def _confirmed_memory(
    *,
    session_id: SessionId,
    repo_id: str,
    memory_type: MemoryType,
    text: str,
) -> MemoryRecord:
    return MemoryRecord(
        memory_id=MemoryId(UUID("00000000-0000-0000-0000-000000000140")),
        memory_type=memory_type,
        text=text,
        confidence=0.9,
        status=MemoryStatus.CONFIRMED,
        visibility=MemoryVisibility.REPO,
        repo_id=repo_id,
        source_session_id=session_id,
        source_event_start=1,
        source_event_end=1,
        created_at=_created_at(),
        updated_at=_created_at(),
    )
