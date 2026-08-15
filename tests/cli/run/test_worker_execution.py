from dataclasses import replace
from pathlib import Path
from uuid import UUID

import pytest
import zebra_agent_cli.cli as cli_module
import zebra_agent_cli.execution as cli_execution
import zebra_agent_cli.run_command_execution as run_command_execution
from agent_core.domain.events import EventType
from agent_core.domain.identifiers import MemoryId, SessionId, new_message_id, new_tool_call_id
from agent_core.domain.memories import MemoryRecord, MemoryStatus, MemoryType, MemoryVisibility
from agent_core.domain.messages import MessageRole, SessionMessage
from agent_core.domain.modeling import (
    ModelCallMetadata,
    ModelCompletion,
    ModelToolDefinition,
    ModelUsage,
)
from agent_core.domain.sessions import SessionStatus
from agent_core.domain.tools import ToolCall
from agent_storage import (
    SQLiteEventStore,
    SQLiteMemoryStore,
    SQLiteProjectionStore,
    SQLiteSkillsStateStore,
)
from agent_tools.skills_catalog import LocalSkillCatalog
from agent_tools.skills_scope import SkillCatalogError, build_scoped_skill_roots
from cli_run_support import (
    FakeGateway,
    _created_at,
    _settings,
)
from zebra_agent_cli.cli import execute
from zebra_agent_config import ZebraAgentSettings


def test_cli_run_command_execute_persists_harness_events(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    database_path = tmp_path / "sessions.sqlite"
    skills = tmp_path / "skills" / "review"
    skills.mkdir(parents=True)
    (skills / "SKILL.md").write_text(
        "---\nname: review\ndescription: Review\nversion: 1.0.0\n---\nGUIDANCE\n",
        encoding="utf-8",
    )
    settings = replace(
        _settings(database_path),
        skill_roots_system=(str(skills.parent),),
        skills_state_path=str(tmp_path / "skills-state.sqlite"),
    )

    def fake_build_model_gateway(settings: ZebraAgentSettings) -> FakeGateway:
        del settings
        return FakeGateway(
            completion=ModelCompletion(
                assistant_message=SessionMessage(
                    message_id=new_message_id(),
                    role=MessageRole.ASSISTANT,
                    content="Repository inspected.",
                    created_at=_created_at(),
                ),
                call_metadata=ModelCallMetadata(
                    provider="test",
                    model_name="test-model",
                    latency_ms=7,
                    usage=ModelUsage(total_tokens=12),
                ),
            )
        )

    monkeypatch.setattr(cli_module, "build_model_gateway", fake_build_model_gateway)
    monkeypatch.setattr("zebra_agent_cli.execution.build_model_gateway", fake_build_model_gateway)

    result = execute(
        [
            "run",
            "Inspect the repository",
            "--execute",
            "--workspace",
            str(tmp_path),
            "--database",
            str(database_path),
        ],
        settings=settings,
    )

    session_id = SessionId(UUID(str(result.payload["session_id"])))
    session = SQLiteProjectionStore(database_path).get_session(session_id)
    events = SQLiteEventStore(database_path).list_for_session(session_id)

    assert result.command == "run"
    assert result.payload["executed"] is True
    assert result.payload["status"] == SessionStatus.COMPLETED.value
    assert result.payload["assistant_message"] == "Repository inspected."
    assert result.payload["policy_profile"] == "workspace_write"
    assert result.payload["workspace_root"] == str(tmp_path.resolve())
    assert [event.event_type for event in events] == [
        EventType.SESSION_CREATED,
        EventType.USER_MESSAGE_RECEIVED,
        EventType.TASK_PREPARED,
        EventType.HARNESS_ATTEMPT_STARTED,
        EventType.MODEL_RESPONSE_RECEIVED,
        EventType.PLAN_PROPOSED,
        EventType.SESSION_COMPLETED,
    ]
    assert session is not None
    assert session.status is SessionStatus.COMPLETED
    prepared = next(event for event in events if event.event_type is EventType.TASK_PREPARED)
    assert prepared.payload["skill_component_identities"] == []


def test_cli_queued_run_does_not_grant_configured_skills_by_default(tmp_path: Path) -> None:
    database_path = tmp_path / "sessions.sqlite"
    skills = tmp_path / "skills" / "review"
    skills.mkdir(parents=True)
    (skills / "SKILL.md").write_text(
        "---\nname: review\ndescription: Review\nversion: 1.0.0\n---\nGUIDANCE\n",
        encoding="utf-8",
    )
    settings = replace(
        _settings(database_path),
        skill_roots=(str(tmp_path / "skills"),),
        skills_state_path=str(tmp_path / "skills-state.sqlite"),
    )

    result = execute(
        ["run", "Queue a task", "--workspace", str(tmp_path), "--database", str(database_path)],
        settings=settings,
    )

    events = SQLiteEventStore(database_path).list_for_session(result.payload["session_id"])
    prepared = next(event for event in events if event.event_type is EventType.TASK_PREPARED)
    assert prepared.payload["skill_components"] == []
    assert prepared.payload["skill_component_identities"] == []

    identity = LocalSkillCatalog((str(skills.parent),)).read("review").metadata.component_identity()
    selected = execute(
        [
            "run",
            "Queue a selected task",
            "--skill",
            "review",
            "--workspace",
            str(tmp_path),
            "--database",
            str(database_path),
        ],
        settings=settings,
    )
    events = SQLiteEventStore(database_path).list_for_session(selected.payload["session_id"])
    prepared = next(event for event in events if event.event_type is EventType.TASK_PREPARED)
    assert prepared.payload["skill_components"] == ["review"]
    assert prepared.payload["skill_component_identities"] == [identity.model_dump(mode="json")]


def test_cli_inspect_shows_frozen_skill_provenance(tmp_path: Path) -> None:
    database_path = tmp_path / "sessions.sqlite"
    skills = tmp_path / "skills" / "review"
    skills.mkdir(parents=True)
    (skills / "SKILL.md").write_text(
        "---\nname: review\ndescription: Review\nversion: 1.0.0\n---\nGUIDANCE\n",
        encoding="utf-8",
    )
    settings = replace(
        _settings(database_path),
        skill_roots_system=(str(skills.parent),),
        skills_state_path=str(tmp_path / "skills-state.sqlite"),
    )
    identity = LocalSkillCatalog(
        build_scoped_skill_roots(system=(str(skills.parent),))
    ).read("review").metadata.component_identity()
    queued = execute(
        [
            "run",
            "Inspect frozen provenance",
            "--skill",
            "review",
            "--workspace",
            str(tmp_path),
            "--database",
            str(database_path),
        ],
        settings=settings,
    )

    inspected = execute(
        ["inspect", str(queued.payload["session_id"]), "--database", str(database_path)],
        settings=settings,
    )

    assert inspected.payload["workspace"]["skill_components"] == ["review"]
    assert inspected.payload["workspace"]["skill_component_identities"] == [
        identity.model_dump(mode="json")
    ]


def test_cli_direct_run_freezes_explicit_system_skill(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    database_path = tmp_path / "sessions.sqlite"
    skills = tmp_path / "skills" / "review"
    skills.mkdir(parents=True)
    (skills / "SKILL.md").write_text(
        "---\nname: review\ndescription: Review\nversion: 1.0.0\n---\nGUIDANCE\n",
        encoding="utf-8",
    )
    settings = replace(
        _settings(database_path),
        skill_roots_system=(str(skills.parent),),
        skills_state_path=str(tmp_path / "skills-state.sqlite"),
    )
    identity = LocalSkillCatalog(
        build_scoped_skill_roots(system=(str(skills.parent),))
    ).read("review").metadata.component_identity()

    def fake_build_model_gateway(settings: ZebraAgentSettings) -> FakeGateway:
        del settings
        return FakeGateway(
            completion=ModelCompletion(
                assistant_message=SessionMessage(
                    message_id=new_message_id(),
                    role=MessageRole.ASSISTANT,
                    content="Selected Skill ran.",
                    created_at=_created_at(),
                )
            )
        )

    monkeypatch.setattr("zebra_agent_cli.execution.build_model_gateway", fake_build_model_gateway)
    result = execute(
        [
            "run",
            "Run a selected task",
            "--execute",
            "--skill",
            "review",
            "--workspace",
            str(tmp_path),
            "--database",
            str(database_path),
        ],
        settings=settings,
    )

    events = SQLiteEventStore(database_path).list_for_session(result.payload["session_id"])
    prepared = next(event for event in events if event.event_type is EventType.TASK_PREPARED)
    assert prepared.payload["skill_components"] == ["review"]
    assert prepared.payload["skill_component_identities"] == [identity.model_dump(mode="json")]


def test_cli_direct_run_freezes_explicit_private_skill(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    database_path = tmp_path / "sessions.sqlite"
    private_root = tmp_path / "private"
    skill = private_root / ".zebra-private" / "owner-a" / "review"
    skill.mkdir(parents=True)
    (skill / "SKILL.md").write_text(
        "---\nname: review\ndescription: Review\nversion: 1.0.0\n---\nPRIVATE\n",
        encoding="utf-8",
    )
    settings = replace(
        _settings(database_path),
        skill_roots=(str(private_root),),
        skills_state_path=str(tmp_path / "skills-state.sqlite"),
    )
    roots = build_scoped_skill_roots(user=(str(private_root),), owner="owner-a")
    catalog = LocalSkillCatalog(roots, inventory_only=True)
    identity = catalog.read("review").metadata.component_identity()
    store = SQLiteSkillsStateStore(settings.skills_state_path)
    store.install_component(
        identity=identity,
        files=catalog.package_files("review"),
        owner="owner-a",
        operator="test",
    )
    store.set_component_enabled(identity=identity, owner="owner-a", enabled=True, operator="test")

    def fake_build_model_gateway(settings: ZebraAgentSettings) -> FakeGateway:
        del settings
        return FakeGateway(
            completion=ModelCompletion(
                assistant_message=SessionMessage(
                    message_id=new_message_id(),
                    role=MessageRole.ASSISTANT,
                    content="Private Skill ran.",
                    created_at=_created_at(),
                )
            )
        )

    monkeypatch.setattr("zebra_agent_cli.execution.build_model_gateway", fake_build_model_gateway)
    result = execute(
        [
            "run",
            "Run a private selected task",
            "--execute",
            "--skill",
            "review",
            "--skill-owner",
            "owner-a",
            "--workspace",
            str(tmp_path),
            "--database",
            str(database_path),
        ],
        settings=settings,
    )

    events = SQLiteEventStore(database_path).list_for_session(result.payload["session_id"])
    prepared = next(event for event in events if event.event_type is EventType.TASK_PREPARED)
    assert prepared.payload["skill_component_identities"] == [identity.model_dump(mode="json")]


def test_cli_direct_owner_only_empty_grant_skips_skill_catalog(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    database_path = tmp_path / "sessions.sqlite"
    private_root = tmp_path / "private"
    private_root.mkdir()
    settings = replace(
        _settings(database_path),
        skill_roots=(str(private_root),),
        skills_state_path=str(tmp_path / "skills-state.sqlite"),
    )

    def fake_build_model_gateway(settings: ZebraAgentSettings) -> FakeGateway:
        del settings
        return FakeGateway(
            completion=ModelCompletion(
                assistant_message=SessionMessage(
                    message_id=new_message_id(),
                    role=MessageRole.ASSISTANT,
                    content="No Skill was granted.",
                    created_at=_created_at(),
                )
            )
        )

    monkeypatch.setattr("zebra_agent_cli.execution.build_model_gateway", fake_build_model_gateway)
    original_execute = run_command_execution.execute_durable_run

    def assert_empty_owner(**kwargs: object):
        assert kwargs["skill_owner"] is None
        return original_execute(**kwargs)

    monkeypatch.setattr(run_command_execution, "execute_durable_run", assert_empty_owner)
    original_harness = cli_execution.run_local_harness

    def assert_no_skill_catalog(**kwargs: object):
        assert kwargs["skill_roots"] == ()
        assert kwargs["skills_state"] is None
        return original_harness(**kwargs)

    monkeypatch.setattr(cli_execution, "run_local_harness", assert_no_skill_catalog)
    result = execute(
        [
            "run",
            "Run without a Skill grant",
            "--execute",
            "--skill-owner",
            "owner-a",
            "--workspace",
            str(tmp_path),
            "--database",
            str(database_path),
        ],
        settings=settings,
    )

    assert result.payload["executed"] is True
    with pytest.raises(SkillCatalogError, match="opaque"):
        execute(
            [
                "run",
                "Reject an invalid owner",
                "--execute",
                "--skill-owner",
                "user",
                "--workspace",
                str(tmp_path),
                "--database",
                str(database_path),
            ],
            settings=settings,
        )


def test_cli_skill_selector_rejects_unavailable_disabled_and_cross_owner(tmp_path: Path) -> None:
    database_path = tmp_path / "sessions.sqlite"
    skills = tmp_path / "skills" / "review"
    skills.mkdir(parents=True)
    (skills / "SKILL.md").write_text(
        "---\nname: review\ndescription: Review\nversion: 1.0.0\n---\nGUIDANCE\n",
        encoding="utf-8",
    )
    settings = replace(
        _settings(database_path),
        skill_roots_system=(str(skills.parent),),
        skills_state_path=str(tmp_path / "skills-state.sqlite"),
    )
    arguments = ["run", "Queue a selected task", "--workspace", str(tmp_path)]
    with pytest.raises(ValueError, match="requested Skill component is unavailable"):
        execute([*arguments, "--skill", "missing"], settings=settings)
    SQLiteSkillsStateStore(settings.skills_state_path).set_enabled(
        name="review", scope="system", enabled=False, operator="test"
    )
    with pytest.raises(ValueError, match="requested Skill component is unavailable"):
        execute([*arguments, "--skill", "review"], settings=settings)

    private_root = tmp_path / "private"
    private_skill = private_root / ".zebra-private" / "owner-a" / "review"
    private_skill.mkdir(parents=True)
    (private_skill / "SKILL.md").write_text(
        "---\nname: review\ndescription: Review\nversion: 1.0.0\n---\nPRIVATE\n",
        encoding="utf-8",
    )
    private_settings = replace(
        _settings(database_path),
        skill_roots=(str(private_root),),
        skills_state_path=str(tmp_path / "private-skills-state.sqlite"),
    )
    owner_a_roots = build_scoped_skill_roots(user=(str(private_root),), owner="owner-a")
    catalog = LocalSkillCatalog(owner_a_roots, inventory_only=True)
    identity = catalog.read("review").metadata.component_identity()
    store = SQLiteSkillsStateStore(private_settings.skills_state_path)
    store.install_component(
        identity=identity,
        files=catalog.package_files("review"),
        owner="owner-a",
        operator="test",
    )
    store.set_component_enabled(identity=identity, owner="owner-a", enabled=True, operator="test")
    selected = execute(
        [*arguments, "--skill", "review", "--skill-owner", "owner-a"],
        settings=private_settings,
    )
    events = SQLiteEventStore(database_path).list_for_session(selected.payload["session_id"])
    prepared = next(event for event in events if event.event_type is EventType.TASK_PREPARED)
    assert prepared.payload["skill_component_identities"] == [identity.model_dump(mode="json")]
    skill_file = private_skill / "SKILL.md"
    skill_file.write_text(
        skill_file.read_text(encoding="utf-8").replace("1.0.0", "2.0.0"),
        encoding="utf-8",
    )
    v2_catalog = LocalSkillCatalog(owner_a_roots, inventory_only=True)
    v2 = v2_catalog.read("review").metadata.component_identity()
    store.install_component(
        identity=v2,
        files=v2_catalog.package_files("review"),
        owner="owner-a",
        operator="test",
    )
    store.set_component_enabled(identity=v2, owner="owner-a", enabled=True, operator="test")
    owner_only = execute([*arguments, "--skill-owner", "owner-a"], settings=private_settings)
    events = SQLiteEventStore(database_path).list_for_session(owner_only.payload["session_id"])
    prepared = next(event for event in events if event.event_type is EventType.TASK_PREPARED)
    assert prepared.payload["skill_component_identities"] == []
    with pytest.raises(ValueError, match="requested Skill component is unavailable"):
        execute(
            [*arguments, "--skill", "review", "--skill-owner", "owner-b"],
            settings=private_settings,
        )

def test_cli_run_command_execute_runs_file_read_tool(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    database_path = tmp_path / "sessions.sqlite"
    (tmp_path / "README.md").write_text("workspace readme\n", encoding="utf-8")

    def fake_build_model_gateway(settings: ZebraAgentSettings) -> FakeGateway:
        del settings
        return FakeGateway(
            completion=ModelCompletion(
                assistant_message=SessionMessage(
                    message_id=new_message_id(),
                    role=MessageRole.ASSISTANT,
                    content="I will read the README.",
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
        )

    monkeypatch.setattr(cli_module, "build_model_gateway", fake_build_model_gateway)
    monkeypatch.setattr("zebra_agent_cli.execution.build_model_gateway", fake_build_model_gateway)

    result = execute(
        [
            "run",
            "Read the README",
            "--execute",
            "--workspace",
            str(tmp_path),
            "--database",
            str(database_path),
        ],
        settings=_settings(database_path),
    )

    assert result.payload["status"] == SessionStatus.COMPLETED.value
    assert result.payload["trace"] == [
        {
            "attempt_number": 1,
            "assistant_message": "Tool result: workspace readme",
            "tools": [
                {
                    "tool_name": "files.read",
                    "status": "executed",
                    "arguments": {"path": "README.md"},
                    "output": "workspace readme\n",
                    "metadata": {
                        "path": "README.md",
                        "byte_count": 17,
                        "truncated": False,
                    },
                    "policy_decision": "allow",
                }
            ],
        }
    ]

def test_cli_run_command_execute_injects_confirmed_memory_into_system_prompt(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    database_path = tmp_path / "sessions.sqlite"
    requests: list[tuple[SessionMessage, ...]] = []
    SQLiteMemoryStore(database_path).upsert(
        MemoryRecord(
            memory_id=MemoryId(UUID("00000000-0000-0000-0000-000000000142")),
            memory_type=MemoryType.PROCEDURE,
            text="Run make check before push.",
            confidence=0.9,
            status=MemoryStatus.CONFIRMED,
            visibility=MemoryVisibility.REPO,
            repo_id=str(tmp_path.resolve()),
            source_session_id=SessionId(UUID("00000000-0000-0000-0000-000000000043")),
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
                        content="CLI execution complete.",
                        created_at=_created_at(),
                    ),
                    call_metadata=ModelCallMetadata(
                        provider="test",
                        model_name="test-model",
                        latency_ms=7,
                        usage=ModelUsage(total_tokens=12),
                    ),
                )

        return RecordingGateway()

    monkeypatch.setattr(cli_module, "build_model_gateway", fake_build_model_gateway)
    monkeypatch.setattr("zebra_agent_cli.execution.build_model_gateway", fake_build_model_gateway)

    result = execute(
        [
            "run",
            "Inspect workspace",
            "--title",
            "CLI execute with memory",
            "--workspace",
            str(tmp_path),
            "--execute",
            "--database",
            str(database_path),
        ],
        settings=_settings(database_path),
    )

    assert result.payload["executed"] is True
    assert requests
    assert requests[0][0].role is MessageRole.SYSTEM
    assert "Procedure 1" in requests[0][0].content
    assert "Run make check before push." in requests[0][0].content
