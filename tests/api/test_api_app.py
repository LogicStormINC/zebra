from dataclasses import replace
from pathlib import Path
from uuid import UUID

import zebra_agent_api.app as api_app_module
from agent_core.domain.events import EventActor, EventType, SessionEvent
from agent_core.domain.identifiers import MemoryId, SessionId, new_message_id, new_tool_call_id
from agent_core.domain.memories import MemoryRecord, MemoryStatus, MemoryType, MemoryVisibility
from agent_core.domain.messages import MessageRole, SessionMessage
from agent_core.domain.modeling import ModelCompletion, ModelToolDefinition
from agent_core.domain.sessions import ApprovalContext, Session, SessionStatus
from agent_core.domain.tools import ToolCall
from agent_core.domain.workspaces import WorkspaceProjection, WorkspaceStatus
from agent_storage import (
    SQLiteEventStore,
    SQLiteMemoryStore,
    SQLiteProjectionStore,
    SQLiteWorkspaceProjectionStore,
)
from zebra_agent_api.app import create_app
from zebra_agent_config import ApiSettings, ModelSettings, ZebraAgentSettings


def test_api_health_returns_service_status(tmp_path: Path) -> None:
    app = create_app(tmp_path / "sessions.sqlite")

    response = app.health()

    assert response.status_code == 200
    assert response.body == {
        "service": "zebra-agent-api",
        "status": "ok",
        "runtime": {
            "profile": "local",
            "runtime_class": "trusted-local",
            "fallback_allowed": False,
            "build_commit": "unknown",
            "task_image_attachments": True,
            "native_image_understanding": False,
            "final_message_identity": True,
            "artifact_output_contract": True,
        },
    }


def test_api_health_reports_native_image_capability_from_explicit_profile(
    tmp_path: Path,
) -> None:
    settings = _settings(tmp_path / "sessions.sqlite")
    settings = replace(
        settings,
        model=replace(
            settings.model,
            provider="qwen",
            model="qwen3.7-flash",
            profile_id="qwen-flash-alias-native-v1",
        ),
    )

    runtime = create_app(settings=settings).health().body["runtime"]

    assert runtime["native_image_understanding"] is True
    assert runtime["profile"] == "test"
    assert runtime["runtime_class"] == "trusted-local"
    assert runtime["fallback_allowed"] is False
    assert runtime["build_commit"] == "unknown"
    assert runtime["task_image_attachments"] is True
    assert runtime["final_message_identity"] is True


def test_api_health_does_not_infer_native_image_capability_without_valid_profile(
    tmp_path: Path,
) -> None:
    settings = _settings(tmp_path / "sessions.sqlite")
    no_profile = replace(
        settings,
        model=replace(settings.model, provider="qwen", model="qwen3.7-flash"),
    )
    text_only = replace(
        settings,
        model=replace(
            settings.model,
            provider="qwen",
            model="qwen3.7-max",
            profile_id="qwen-max-text-v1",
        ),
    )

    assert (
        create_app(settings=no_profile).health().body["runtime"]["native_image_understanding"]
        is False
    )
    assert (
        create_app(settings=text_only).health().body["runtime"]["native_image_understanding"]
        is False
    )


def test_api_health_fails_closed_for_invalid_model_profile(tmp_path: Path) -> None:
    settings = _settings(tmp_path / "sessions.sqlite")
    unknown = replace(
        settings,
        model=replace(
            settings.model,
            provider="qwen",
            model="qwen3.7-flash",
            profile_id="unknown-profile",
        ),
    )
    mismatch = replace(
        settings,
        model=replace(
            settings.model,
            provider="qwen",
            model="qwen3.7-flash-2026-07-15",
            profile_id="qwen-flash-alias-native-v1",
        ),
    )

    assert (
        create_app(settings=unknown).health().body["runtime"]["native_image_understanding"] is False
    )
    assert (
        create_app(settings=mismatch).health().body["runtime"]["native_image_understanding"]
        is False
    )


def test_api_health_reports_the_configured_build_commit(tmp_path: Path) -> None:
    settings = replace(_settings(tmp_path / "sessions.sqlite"), build_commit="37708b4")

    assert create_app(settings=settings).health().body["runtime"]["build_commit"] == "37708b4"


def test_api_create_app_uses_settings_database_by_default(tmp_path: Path) -> None:
    database_path = tmp_path / "configured.sqlite"
    app = create_app(settings=_settings(database_path))

    assert app.database_path == database_path


def test_api_create_app_database_path_overrides_settings(tmp_path: Path) -> None:
    configured_path = tmp_path / "configured.sqlite"
    explicit_path = tmp_path / "explicit.sqlite"
    app = create_app(explicit_path, settings=_settings(configured_path))

    assert app.database_path == explicit_path


def test_api_get_session_returns_projection(tmp_path: Path) -> None:
    database_path = tmp_path / "sessions.sqlite"
    session = SQLiteProjectionStore(database_path).save_session(Session.create(title="API session"))

    response = create_app(database_path).get_session(str(session.session_id))

    assert response.status_code == 200
    assert response.body == {
        "session_id": str(session.session_id),
        "title": "API session",
        "status": SessionStatus.CREATED.value,
        "current_sequence": 0,
    }


def test_api_get_session_includes_workspace_projection_when_available(tmp_path: Path) -> None:
    database_path = tmp_path / "sessions.sqlite"
    session = SQLiteProjectionStore(database_path).save_session(
        Session.create(title="Workspace readback").model_copy(
            update={
                "status": SessionStatus.SUSPENDED,
                "current_sequence": 4,
            }
        )
    )
    SQLiteWorkspaceProjectionStore(database_path).save_workspace(
        WorkspaceProjection.model_validate(
            {
                "session_id": session.session_id,
                "workspace_root": str(tmp_path.resolve()),
                "prepared_at": _created_at(),
                "updated_at": _created_at(),
                "current_sequence": 4,
                "status": WorkspaceStatus.SUSPENDED,
                "policy_profile": "workspace_write",
                "last_attempt_number": 1,
                "runtime_name": "local",
                "snapshot_id": "snap-123",
                "snapshot_path": "/tmp/zebra-agent-runtime/snap-123",
            }
        )
    )

    response = create_app(database_path).get_session(str(session.session_id))

    assert response.status_code == 200
    assert response.body["workspace"] == {
        "workspace_root": str(tmp_path.resolve()),
        "tool_profile": "coding",
        "network_profile": "none",
        "network_allowlist": [],
        "status": "suspended",
        "current_sequence": 4,
        "prepared_at": _created_at().isoformat(),
        "updated_at": _created_at().isoformat(),
        "policy_profile": "workspace_write",
        "last_attempt_number": 1,
        "runtime_name": "local",
        "snapshot": {
            "runtime_name": "local",
            "snapshot_id": "snap-123",
            "snapshot_path": "/tmp/zebra-agent-runtime/snap-123",
        },
    }


def test_api_get_session_returns_not_found(tmp_path: Path) -> None:
    response = create_app(tmp_path / "sessions.sqlite").get_session(
        "00000000-0000-0000-0000-000000000001"
    )

    assert response.status_code == 404
    assert response.body == {
        "session_id": "00000000-0000-0000-0000-000000000001",
        "status": "not_found",
    }


def test_api_get_session_rejects_invalid_session_id(tmp_path: Path) -> None:
    response = create_app(tmp_path / "sessions.sqlite").get_session("not-a-valid-uuid")

    assert response.status_code == 400
    assert response.body == {
        "session_id": "not-a-valid-uuid",
        "status": "invalid_request",
        "reason": "session_id must be a valid UUID",
    }


def test_api_lists_waiting_approvals_from_projection(tmp_path: Path) -> None:
    database_path = tmp_path / "sessions.sqlite"
    first = _waiting_session("First approval").model_copy(update={"current_sequence": 3})
    second = _waiting_session("Second approval").model_copy(
        update={
            "current_sequence": 4,
            "updated_at": _created_at().replace(second=21),
        }
    )
    SQLiteProjectionStore(database_path).save_session(first)
    SQLiteProjectionStore(database_path).save_session(second)

    response = create_app(database_path).list_approvals()

    assert response.status_code == 200
    assert response.body["approvals"][0]["approval_id"] == str(first.session_id)
    assert response.body["approvals"][1]["approval_id"] == str(second.session_id)
    assert response.body["approvals"][0]["approval_context"]["route"] == "mcp_proxy"


def test_api_get_approval_returns_projection_detail(tmp_path: Path) -> None:
    database_path = tmp_path / "sessions.sqlite"
    session = _waiting_session("Approval detail").model_copy(update={"current_sequence": 5})
    SQLiteProjectionStore(database_path).save_session(session)

    response = create_app(database_path).get_approval(str(session.session_id))

    assert response.status_code == 200
    assert response.body["approval_id"] == str(session.session_id)
    assert response.body["title"] == "Approval detail"
    assert response.body["approval_context"]["route"] == "mcp_proxy"


def test_api_get_session_stream_returns_persisted_events(tmp_path: Path) -> None:
    database_path = tmp_path / "sessions.sqlite"
    session = Session.create(title="API stream")
    projection_store = SQLiteProjectionStore(database_path)
    projection_store.save_session(session)
    from agent_storage import SQLiteEventStore

    event_store = SQLiteEventStore(database_path)
    created = event_store.append(
        SessionEvent.create(
            session_id=session.session_id,
            sequence=0,
            event_type=EventType.SESSION_CREATED,
            actor=EventActor.USER,
            payload={"title": session.title},
        )
    )
    prepared = event_store.append(
        SessionEvent.create(
            session_id=session.session_id,
            sequence=1,
            event_type=EventType.TASK_PREPARED,
            actor=EventActor.HARNESS,
            payload={
                "title": session.title,
                "user_input": "stream me",
            },
        )
    )

    response = create_app(database_path).get_session_stream(str(session.session_id))

    assert response.status_code == 200
    assert response.body["session_id"] == str(session.session_id)
    assert response.body["events"] == [
        {
            "event_id": str(created.event_id),
            "sequence": 0,
            "event_type": EventType.SESSION_CREATED.value,
            "actor": EventActor.USER.value,
            "created_at": created.created_at.isoformat(),
            "payload": {"title": session.title},
        },
        {
            "event_id": str(prepared.event_id),
            "sequence": 1,
            "event_type": EventType.TASK_PREPARED.value,
            "actor": EventActor.HARNESS.value,
            "created_at": prepared.created_at.isoformat(),
            "payload": {
                "title": session.title,
                "user_input": "stream me",
                "workspace_root": None,
                "policy_profile": None,
                "tool_profile": None,
                "network_profile": None,
                "network_allowlist": None,
                "max_attempts": None,
                "max_corrections_per_attempt": None,
                "max_model_calls": None,
                "max_tool_calls": None,
            },
        },
    ]


def test_api_get_session_stream_returns_not_found(tmp_path: Path) -> None:
    response = create_app(tmp_path / "sessions.sqlite").get_session_stream(
        "00000000-0000-0000-0000-000000000001"
    )

    assert response.status_code == 404
    assert response.body == {
        "session_id": "00000000-0000-0000-0000-000000000001",
        "status": "not_found",
    }


def test_api_get_session_stream_rejects_invalid_session_id(tmp_path: Path) -> None:
    response = create_app(tmp_path / "sessions.sqlite").get_session_stream("not-a-valid-uuid")

    assert response.status_code == 400
    assert response.body == {
        "session_id": "not-a-valid-uuid",
        "status": "invalid_request",
        "reason": "session_id must be a valid UUID",
    }


def test_api_create_session_persists_created_session(tmp_path: Path) -> None:
    database_path = tmp_path / "sessions.sqlite"

    response = create_app(database_path, settings=_settings(database_path)).create_session(
        {
            "prompt": "Inspect the workspace",
            "title": "API create session",
        }
    )

    session = SQLiteProjectionStore(database_path).get_session(
        SessionId(response.body["session_id"])
    )

    assert response.status_code == 201
    assert response.body["executed"] is False
    assert response.body["tool_profile"] == "general"
    assert response.body["network_profile"] == "none"
    assert response.body["network_allowlist"] == []
    assert response.body["status"] == SessionStatus.READY.value
    assert session is not None
    assert session.title == "API create session"
    assert session.status is SessionStatus.READY
    detail = create_app(database_path).get_session(response.body["session_id"])
    assert detail.body["workspace"]["tool_profile"] == "general"
    assert detail.body["workspace"]["network_profile"] == "none"


def test_api_create_session_persists_explicit_history_scope(tmp_path: Path) -> None:
    database_path = tmp_path / "sessions.sqlite"
    history_session_id = "00000000-0000-0000-0000-000000000001"

    response = create_app(database_path, settings=_settings(database_path)).create_session(
        {
            "prompt": "Continue only this prior task",
            "history_session_ids": [history_session_id],
            "max_model_calls": 8,
            "max_tool_calls": 8,
        }
    )
    events = SQLiteEventStore(database_path).list_for_session(
        SessionId(response.body["session_id"])
    )

    assert response.status_code == 201
    assert response.body["history_session_ids"] == [history_session_id]
    assert response.body["max_model_calls"] == 8
    assert response.body["max_tool_calls"] == 8
    assert events[2].payload["history_session_ids"] == [history_session_id]
    assert events[2].payload["max_model_calls"] == 8
    assert events[2].payload["max_tool_calls"] == 8


def test_api_create_session_accepts_larger_tool_budget_for_material_harness(
    tmp_path: Path,
) -> None:
    database_path = tmp_path / "sessions.sqlite"

    response = create_app(database_path, settings=_settings(database_path)).create_session(
        {
            "prompt": "Inspect a chunked material bundle",
            "max_model_calls": 16,
            "max_tool_calls": 28,
        }
    )

    assert response.status_code == 201
    assert response.body["max_model_calls"] == 16
    assert response.body["max_tool_calls"] == 28


def test_api_create_session_persists_domain_allowlist(tmp_path: Path) -> None:
    database_path = tmp_path / "sessions.sqlite"

    response = create_app(database_path, settings=_settings(database_path)).create_session(
        {
            "prompt": "Read allowed documentation",
            "network_profile": "domain-allowlist",
            "network_allowlist": ["Docs.Example.com", "docs.example.com"],
        }
    )

    assert response.status_code == 201
    assert response.body["network_profile"] == "domain-allowlist"
    assert response.body["network_allowlist"] == ["docs.example.com"]
    detail = create_app(database_path).get_session(response.body["session_id"])
    assert detail.body["workspace"]["network_allowlist"] == ["docs.example.com"]


def test_api_create_session_execute_persists_harness_events(
    tmp_path: Path,
    monkeypatch,
) -> None:
    database_path = tmp_path / "sessions.sqlite"
    original_run_local_harness = api_app_module.run_local_harness
    captured_budgets: dict[str, int | None] = {}

    def capture_budgets(**kwargs):
        captured_budgets.update(
            max_model_calls=kwargs["max_model_calls"],
            max_tool_calls=kwargs["max_tool_calls"],
        )
        return original_run_local_harness(**kwargs)

    def fake_build_model_gateway(settings: ZebraAgentSettings):
        del settings
        from agent_core.application.mock_model import ScriptedModelGateway, ScriptedModelResponse

        return ScriptedModelGateway(
            responses=(
                ScriptedModelResponse(
                    completion=ModelCompletion(
                        assistant_message=SessionMessage(
                            message_id=new_message_id(),
                            role=MessageRole.ASSISTANT,
                            content="API execution complete.",
                            created_at=_created_at(),
                        )
                    )
                ),
                ScriptedModelResponse(
                    completion=ModelCompletion(
                        assistant_message=SessionMessage(
                            message_id=new_message_id(),
                            role=MessageRole.ASSISTANT,
                            content="README content: api readme",
                            created_at=_created_at(),
                        )
                    )
                ),
            )
        )

    monkeypatch.setattr(api_app_module, "build_model_gateway", fake_build_model_gateway)
    monkeypatch.setattr(api_app_module, "run_local_harness", capture_budgets)

    response = create_app(database_path, settings=_settings(database_path)).create_session(
        {
            "prompt": "Inspect the workspace",
            "title": "API execute session",
            "workspace": str(tmp_path),
            "execute": True,
            "max_model_calls": 7,
            "max_tool_calls": 9,
        }
    )

    session = SQLiteProjectionStore(database_path).get_session(
        SessionId(response.body["session_id"])
    )

    assert response.status_code == 201
    assert response.body["executed"] is True
    assert response.body["status"] == SessionStatus.COMPLETED.value
    assert response.body["assistant_message"] == "API execution complete."
    assert response.body["trace"] == [
        {
            "attempt_number": 1,
            "assistant_message": "API execution complete.",
            "tools": [],
        }
    ]
    assert session is not None
    assert session.status is SessionStatus.COMPLETED
    assert captured_budgets == {"max_model_calls": 7, "max_tool_calls": 9}


def test_api_create_session_execute_runs_builtin_tool(
    tmp_path: Path,
    monkeypatch,
) -> None:
    database_path = tmp_path / "sessions.sqlite"
    (tmp_path / "README.md").write_text("api readme\n", encoding="utf-8")

    def fake_build_model_gateway(settings: ZebraAgentSettings):
        del settings
        from agent_core.application.mock_model import ScriptedModelGateway, ScriptedModelResponse

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
                    )
                ),
                ScriptedModelResponse(
                    completion=ModelCompletion(
                        assistant_message=SessionMessage(
                            message_id=new_message_id(),
                            role=MessageRole.ASSISTANT,
                            content="README content: api readme",
                            created_at=_created_at(),
                        )
                    )
                ),
                ScriptedModelResponse(
                    completion=ModelCompletion(
                        assistant_message=SessionMessage(
                            message_id=new_message_id(),
                            role=MessageRole.ASSISTANT,
                            content="README content: api readme",
                            created_at=_created_at(),
                        )
                    )
                ),
            )
        )

    monkeypatch.setattr(api_app_module, "build_model_gateway", fake_build_model_gateway)

    response = create_app(database_path, settings=_settings(database_path)).create_session(
        {
            "prompt": "Read the README",
            "workspace": str(tmp_path),
            "execute": True,
        }
    )

    assert response.status_code == 201
    assert response.body["trace"] == [
        {
            "attempt_number": 1,
            "assistant_message": "README content: api readme",
            "tools": [
                {
                    "tool_name": "files.read",
                    "status": "executed",
                    "arguments": {"path": "README.md"},
                    "output": "api readme\n",
                    "metadata": {
                        "path": "README.md",
                        "byte_count": 11,
                        "truncated": False,
                    },
                    "policy_decision": "allow",
                    "policy_route": None,
                    "policy_target": None,
                    "policy_network_profile": None,
                    "policy_scope": [],
                }
            ],
        }
    ]


def test_api_create_session_execute_injects_confirmed_memory_into_system_prompt(
    tmp_path: Path,
    monkeypatch,
) -> None:
    database_path = tmp_path / "sessions.sqlite"
    requests: list[tuple[SessionMessage, ...]] = []
    SQLiteMemoryStore(database_path).upsert(
        MemoryRecord(
            memory_id=MemoryId(UUID("00000000-0000-0000-0000-000000000141")),
            memory_type=MemoryType.PROCEDURE,
            text="Run make check before push.",
            confidence=0.9,
            status=MemoryStatus.CONFIRMED,
            visibility=MemoryVisibility.REPO,
            repo_id=str(tmp_path.resolve()),
            source_session_id=SessionId(UUID("00000000-0000-0000-0000-000000000042")),
            created_at=_created_at(),
            updated_at=_created_at(),
        )
    )

    def fake_build_model_gateway(settings: ZebraAgentSettings):
        del settings

        class RecordingGateway:
            def complete(
                self,
                messages: list[SessionMessage],
                *,
                tools: tuple[ModelToolDefinition, ...] = (),
            ) -> ModelCompletion:
                assert tools
                requests.append(tuple(messages))
                return ModelCompletion(
                    assistant_message=SessionMessage(
                        message_id=new_message_id(),
                        role=MessageRole.ASSISTANT,
                        content="API execution complete.",
                        created_at=_created_at(),
                    )
                )

        return RecordingGateway()

    monkeypatch.setattr(api_app_module, "build_model_gateway", fake_build_model_gateway)

    response = create_app(database_path, settings=_settings(database_path)).create_session(
        {
            "prompt": "Inspect the workspace",
            "title": "API execute session with memory",
            "workspace": str(tmp_path),
            "execute": True,
        }
    )

    assert response.status_code == 201
    assert requests
    assert requests[0][0].role is MessageRole.SYSTEM
    assert "Procedure 1" in requests[0][0].content
    assert "Run make check before push." in requests[0][0].content


def test_api_create_session_rejects_invalid_request(tmp_path: Path) -> None:
    database_path = tmp_path / "sessions.sqlite"

    response = create_app(database_path, settings=_settings(database_path)).create_session(
        {"prompt": "   "}
    )

    assert response.status_code == 400
    assert response.body == {
        "status": "invalid_request",
        "reason": "prompt must be a non-blank string",
    }

    invalid_profile = create_app(database_path, settings=_settings(database_path)).create_session(
        {"prompt": "Continue", "tool_profile": "unknown"}
    )

    assert invalid_profile.status_code == 400
    assert invalid_profile.body == {
        "status": "invalid_request",
        "reason": "tool_profile is not supported",
    }

    invalid_network = create_app(database_path, settings=_settings(database_path)).create_session(
        {"prompt": "Continue", "network_profile": "domain-allowlist"}
    )

    assert invalid_network.status_code == 400
    assert "requires at least one allowed domain" in str(invalid_network.body["reason"])

    invalid_history = create_app(database_path, settings=_settings(database_path)).create_session(
        {"prompt": "Continue", "history_session_ids": ["not-a-uuid"]}
    )

    assert invalid_history.status_code == 400
    assert invalid_history.body["reason"] == ("history_session_ids must contain UUID strings")


def test_api_create_session_execute_reports_missing_api_key(
    tmp_path: Path,
    monkeypatch,
) -> None:
    database_path = tmp_path / "sessions.sqlite"

    def fake_build_model_gateway(_: ZebraAgentSettings) -> object:
        del _
        raise ValueError("missing API key in environment variable TEST_API_KEY")

    monkeypatch.setattr(api_app_module, "build_model_gateway", fake_build_model_gateway)

    response = create_app(database_path, settings=_settings(database_path)).create_session(
        {
            "prompt": "Inspect the workspace",
            "title": "API execute session",
            "workspace": str(tmp_path),
            "execute": True,
        }
    )

    assert response.status_code == 503
    assert response.body["status"] == "model_gateway_unavailable"
    assert response.body["reason"] == "missing API key in environment variable TEST_API_KEY"


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


def _created_at():
    from datetime import UTC, datetime

    return datetime(2026, 6, 22, 13, 20, tzinfo=UTC)


def _waiting_session(title: str) -> Session:
    return Session.create(title=title, created_at=_created_at()).model_copy(
        update={
            "status": SessionStatus.WAITING_APPROVAL,
            "approval_context": ApprovalContext(
                tool_name="mcp.github.create_pull_request",
                reason="proxy-routed external tool execution in test",
                policy_profile="full_access",
                route="mcp_proxy",
                target="github.create_pull_request",
                network_profile="mcp-proxy-only",
                scope=(
                    "tool:mcp.github.create_pull_request",
                    "route:mcp_proxy",
                ),
            ),
        }
    )
