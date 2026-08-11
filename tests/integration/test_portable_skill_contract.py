from datetime import UTC, datetime
from pathlib import Path

import pytest
from agent_core.application.mock_model import ScriptedModelGateway, ScriptedModelResponse
from agent_core.application.workspace_projection import rebuild_workspace
from agent_core.domain.attachments import AttachmentContextInput
from agent_core.domain.events import EventType
from agent_core.domain.identifiers import new_artifact_id, new_message_id, new_tool_call_id
from agent_core.domain.messages import MessageRole, SessionMessage
from agent_core.domain.modeling import ModelCompletion
from agent_core.domain.policies import PolicyDecisionType
from agent_core.domain.tools import ToolCall, ToolCallStatus
from agent_runtime import LocalToolGateway, run_local_harness
from agent_security import LocalPolicyEngine, PolicyProfile
from agent_storage import (
    SQLiteArtifactPayloadStore,
    SQLiteEventStore,
    SQLiteSkillsStateStore,
    SQLiteWorkspaceProjectionStore,
)
from agent_tools.skills_catalog import LocalSkillCatalog, SkillCatalogError, SkillMetadata
from agent_tools.skills_scope import ScopedSkillRoot, SkillScope
from zebra_agent_api.app import create_app
from zebra_agent_config import ApiSettings, ModelSettings, ZebraAgentSettings
from zebra_agent_worker.task_recovery import recover_task

NOW = datetime(2026, 8, 8, 8, 0, tzinfo=UTC)
SKILL_NAME = "portable-review"
SKILL_VERSION = "1.0.0"
ATTACHMENT_MARKER = "ATTACHMENT-ONLY-PORTABLE-REVIEW"


def test_system_and_user_skills_share_runtime_and_policy_under_the_same_grant(
    tmp_path: Path,
) -> None:
    system_root = tmp_path / "system"
    user_root = tmp_path / "user"
    _write_skill(system_root, "system-core")
    _write_skill(user_root, "user-core")
    system_gateway = _gateway(
        tmp_path / "system-workspace",
        ScopedSkillRoot(
            scope=SkillScope.SYSTEM,
            root=str(system_root),
            namespace="platform",
        ),
    )
    user_gateway = _gateway(
        tmp_path / "user-workspace",
        ScopedSkillRoot(
            scope=SkillScope.USER,
            root=str(user_root),
            namespace="private",
        ),
    )

    try:
        assert _tool_names(system_gateway) == _tool_names(user_gateway)
        assert system_gateway.effective_skill_components == (SKILL_NAME,)
        assert user_gateway.effective_skill_components == (SKILL_NAME,)

        system_read = system_gateway.execute(_call("skills.read", {"name": SKILL_NAME}))
        user_read = user_gateway.execute(_call("skills.read", {"name": SKILL_NAME}))

        assert system_read.status is ToolCallStatus.EXECUTED
        assert user_read.status is ToolCallStatus.EXECUTED
        assert system_read.output == user_read.output
        assert system_read.metadata["skill_scope"] == "system"
        assert user_read.metadata["skill_scope"] == "user"
        assert system_read.metadata["source"] != user_read.metadata["source"]

        policy = LocalPolicyEngine(profile=PolicyProfile.READ_ONLY)
        denied = _call("patch.apply", {"patch": "diff --git a/a b/a"})
        assert policy.evaluate_tool_call(denied).decision is PolicyDecisionType.DENY
        assert policy.evaluate_tool_call(denied).decision is PolicyDecisionType.DENY
    finally:
        system_gateway.close()
        user_gateway.close()


def test_skill_source_does_not_add_authority(tmp_path: Path) -> None:
    root = tmp_path / "skills"
    _write_skill(
        root,
        "core",
        extra_frontmatter="required_capability: portfolio_positions\n",
        body="Use a semantic input role when it is already provided.\n",
    )
    gateway = _gateway(
        tmp_path / "workspace",
        ScopedSkillRoot(scope=SkillScope.SYSTEM, root=str(root)),
    )

    try:
        assert "host.positions.read" not in _tool_names(gateway)
        result = gateway.execute(_call("host.positions.read", {}))
        assert result.status is ToolCallStatus.FAILED
        assert result.metadata["reason"] == "tool_validation_error"
        decision = LocalPolicyEngine(profile=PolicyProfile.READ_ONLY).evaluate_tool_call(
            _call("host.positions.read", {})
        )
        assert decision.decision is PolicyDecisionType.DENY
    finally:
        gateway.close()


def test_attachment_only_portable_core_runs_without_host_specific_tools(tmp_path: Path) -> None:
    root = tmp_path / "skills"
    _write_skill(root, "core")
    skill_root = ScopedSkillRoot(scope=SkillScope.USER, root=str(root), namespace="private")
    model = ScriptedModelGateway(
        (
            ScriptedModelResponse(
                ModelCompletion(
                    assistant_message=_message("Read the portable guidance."),
                    tool_calls=(_call("skills.read", {"name": SKILL_NAME}),),
                )
            ),
            ScriptedModelResponse(ModelCompletion(assistant_message=_message("Review complete."))),
            ScriptedModelResponse(ModelCompletion(assistant_message=_message("Review complete."))),
        )
    )

    result = run_local_harness(
        prompt="Review the attached trade data.",
        title="Attachment-only portable review",
        workspace_root=tmp_path,
        model_gateway=model,
        policy_profile=PolicyProfile.READ_ONLY,
        skill_roots=(skill_root,),
        attachments=(
            AttachmentContextInput(
                attachment_id=new_artifact_id(),
                file_name="trades.csv",
                media_type="text/csv",
                text=ATTACHMENT_MARKER,
            ),
        ),
    )

    assert result.session.status.value == "completed"
    assert ATTACHMENT_MARKER in model.requests[0][0].content
    assert "skills.read" in {tool.name for tool in model.tool_requests[0]}
    assert not {tool.name for tool in model.tool_requests[0] if tool.name.startswith("finos.")}


def test_missing_host_capability_fails_closed_without_a_fallback(tmp_path: Path) -> None:
    root = tmp_path / "skills"
    _write_skill(root, "core")
    gateway = _gateway(
        tmp_path / "workspace",
        ScopedSkillRoot(scope=SkillScope.USER, root=str(root)),
    )

    try:
        unavailable = "mcp.alternate.positions"
        assert unavailable not in _tool_names(gateway)
        result = gateway.execute(_call(unavailable, {}))
        assert result.status is ToolCallStatus.FAILED
        assert result.metadata["reason"] == "tool_validation_error"
    finally:
        gateway.close()


def test_semantic_roles_do_not_create_grants_or_prefer_a_host_name(tmp_path: Path) -> None:
    root = tmp_path / "skills"
    _write_skill(
        root,
        "core",
        body="Input role: portfolio_positions. Use any already granted equivalent input.\n",
    )
    gateway = _gateway(
        tmp_path / "workspace",
        ScopedSkillRoot(scope=SkillScope.USER, root=str(root)),
    )
    policy = LocalPolicyEngine(profile=PolicyProfile.READ_ONLY)

    try:
        for tool_name in ("mcp.alpha.positions", "mcp.beta.positions"):
            assert tool_name not in _tool_names(gateway)
            decision = policy.evaluate_tool_call(_call(tool_name, {}))
            assert decision.decision is PolicyDecisionType.DENY
    finally:
        gateway.close()


def test_output_contract_without_a_host_persistence_command_has_no_business_side_effect(
    tmp_path: Path,
) -> None:
    root = tmp_path / "skills"
    _write_skill(root, "core")
    gateway = _gateway(
        tmp_path / "workspace",
        ScopedSkillRoot(scope=SkillScope.USER, root=str(root)),
    )
    envelope = {
        "contract_id": "portable.review.candidate",
        "contract_version": "1",
        "structured_payload": {"summary": "candidate only"},
        "source_refs": ["attachment://trades.csv"],
    }

    try:
        assert not {name for name in _tool_names(gateway) if name.startswith("finos.")}
        emitted = gateway.execute(
            _call("artifact.output_contract.emit", {"output_contract": envelope})
        )
        assert emitted.status is ToolCallStatus.EXECUTED
        assert emitted.metadata["output_contract"] == envelope
        assert emitted.metadata["side_effect"] == "artifact_metadata"

        save_attempt = gateway.execute(_call("host.review.save", {}))
        assert save_attempt.status is ToolCallStatus.FAILED
        assert save_attempt.metadata["reason"] == "tool_validation_error"
    finally:
        gateway.close()


def test_actual_skills_read_provenance_has_version_digest_scope_and_source(tmp_path: Path) -> None:
    root = tmp_path / "skills"
    _write_skill(root, "portable/core")
    scoped_root = ScopedSkillRoot(scope=SkillScope.USER, root=str(root), namespace="private")
    expected = LocalSkillCatalog((scoped_root,)).read(SKILL_NAME).metadata

    result = _run_skill_read(tmp_path, scoped_root)

    read_event = next(
        event
        for event in result.events
        if event.event_type is EventType.TOOL_EXECUTION_COMPLETED
        and event.payload["tool_name"] == "skills.read"
    )
    metadata = read_event.payload["metadata"]
    assert metadata["skill_name"] == expected.name
    assert metadata["skill_version"] == expected.version
    assert metadata["skill_digest"] == expected.digest
    assert metadata["skill_scope"] == expected.scope.value
    assert metadata["provenance_source"] == expected.source
    assert metadata["skill_component_identity"] == _identity_mapping(expected)


def test_task_grant_records_the_stable_actual_skill_component_identity(tmp_path: Path) -> None:
    root = tmp_path / "skills"
    _write_skill(root, "portable/core")
    scoped_root = ScopedSkillRoot(scope=SkillScope.USER, root=str(root), namespace="private")
    expected = LocalSkillCatalog((scoped_root,)).read(SKILL_NAME).metadata

    result = _run_skill_read(tmp_path, scoped_root)
    prepared = next(event for event in result.events if event.event_type is EventType.TASK_PREPARED)

    assert prepared.payload["skill_component_identities"] == [_identity_mapping(expected)]


def test_resume_preserves_skill_identity_when_the_catalog_drifts(tmp_path: Path) -> None:
    root = tmp_path / "skills"
    skill_file = _write_skill(root, "portable/core")
    scoped_root = ScopedSkillRoot(scope=SkillScope.USER, root=str(root), namespace="private")
    initial_metadata = LocalSkillCatalog((scoped_root,)).read(SKILL_NAME).metadata
    initial = _run_skill_read(tmp_path, scoped_root)
    workspace = rebuild_workspace(list(initial.events))

    skill_file.write_text(
        skill_file.read_text(encoding="utf-8").replace("1.0.0", "2.0.0"),
        encoding="utf-8",
    )
    current_metadata = LocalSkillCatalog((scoped_root,)).read(SKILL_NAME).metadata
    recovered = recover_task(
        list(initial.events),
        workspace=workspace,
        fallback_title="fallback",
        attachment_store=SQLiteArtifactPayloadStore(tmp_path / "artifacts.sqlite"),
    )

    assert current_metadata.digest != initial_metadata.digest
    assert [
        identity.model_dump(mode="json")
        for identity in recovered.skill_component_identities or ()
    ] == [_identity_mapping(initial_metadata)]
    with pytest.raises(SkillCatalogError, match="granted skill component identity"):
        LocalToolGateway(
            tmp_path / "resumed-workspace",
            policy_profile=PolicyProfile.READ_ONLY,
            skill_roots=(scoped_root,),
            granted_skill_component_identities=recovered.skill_component_identities,
        )


def test_queued_task_persists_identity_through_workspace_projection(tmp_path: Path) -> None:
    root = tmp_path / "skills"
    _write_skill(root, "portable/core")
    scoped_root = ScopedSkillRoot(scope=SkillScope.USER, root=str(root), namespace="user")
    expected = LocalSkillCatalog((scoped_root,)).read(SKILL_NAME).metadata
    database_path = tmp_path / "sessions.sqlite"
    settings = ZebraAgentSettings(
        profile="test",
        database_url=str(database_path),
        api=ApiSettings(auth_token=None),
        model=ModelSettings(
            provider="test",
            api_key_env="TEST_API_KEY",
            base_url="https://example.test",
            model="test-model",
        ),
        skill_roots=(str(root),),
        skills_state_path=str(tmp_path / "skills-state.sqlite"),
    )

    response = create_app(database_path, settings=settings).create_session(
        {
            "prompt": "Run the portable review.",
            "workspace": str(tmp_path),
            "execute": False,
            "skill_components": [SKILL_NAME],
        }
    )

    assert response.status_code == 201
    session_id = response.body["session_id"]
    events = SQLiteEventStore(database_path).list_for_session(session_id)
    prepared = next(event for event in events if event.event_type is EventType.TASK_PREPARED)
    assert prepared.payload["skill_component_identities"] == [_identity_mapping(expected)]
    workspace = SQLiteWorkspaceProjectionStore(database_path).get_workspace(session_id)
    assert workspace is not None
    assert [
        identity.model_dump(mode="json")
        for identity in workspace.skill_component_identities or ()
    ] == [_identity_mapping(expected)]


def test_legacy_user_identity_remains_pinnable_with_state(tmp_path: Path) -> None:
    root = tmp_path / "skills"
    _write_skill(root, "portable/core")
    scoped_root = ScopedSkillRoot(scope=SkillScope.USER, root=str(root), namespace="user")
    identity = LocalSkillCatalog((scoped_root,)).read(SKILL_NAME).metadata.component_identity()
    gateway = LocalToolGateway(
        tmp_path / "workspace",
        policy_profile=PolicyProfile.READ_ONLY,
        skill_roots=(scoped_root,),
        skills_state=SQLiteSkillsStateStore(tmp_path / "skills-state.sqlite"),
        granted_skill_component_identities=(identity,),
    )
    try:
        result = gateway.execute(_call("skills.read", {"name": SKILL_NAME}))
        assert result.status is ToolCallStatus.EXECUTED
    finally:
        gateway.close()


def test_empty_new_task_grant_stays_empty_when_a_skill_is_enabled_later(
    tmp_path: Path,
) -> None:
    root = tmp_path / "skills"
    _write_skill(root, "portable/core")
    database_path = tmp_path / "sessions.sqlite"
    skills_state_path = tmp_path / "skills-state.sqlite"
    state = SQLiteSkillsStateStore(skills_state_path)
    state.set_enabled(name=SKILL_NAME, scope="user", enabled=False, operator="test")
    settings = ZebraAgentSettings(
        profile="test",
        database_url=str(database_path),
        api=ApiSettings(auth_token=None),
        model=ModelSettings(
            provider="test",
            api_key_env="TEST_API_KEY",
            base_url="https://example.test",
            model="test-model",
        ),
        skill_roots=(str(root),),
        skills_state_path=str(skills_state_path),
    )

    response = create_app(database_path, settings=settings).create_session(
        {
            "prompt": "Run the portable review.",
            "workspace": str(tmp_path),
            "execute": False,
        }
    )

    assert response.status_code == 201
    session_id = response.body["session_id"]
    events = SQLiteEventStore(database_path).list_for_session(session_id)
    prepared = next(event for event in events if event.event_type is EventType.TASK_PREPARED)
    assert prepared.payload["skill_component_identities"] == []
    workspace = SQLiteWorkspaceProjectionStore(database_path).get_workspace(session_id)
    assert workspace is not None
    assert workspace.skill_component_identities == ()

    state.set_enabled(name=SKILL_NAME, scope="user", enabled=True, operator="test")
    gateway = LocalToolGateway(
        tmp_path / "resumed-workspace",
        policy_profile=PolicyProfile.READ_ONLY,
        skill_roots=(ScopedSkillRoot(scope=SkillScope.USER, root=str(root)),),
        skills_state=state,
        granted_skill_component_identities=workspace.skill_component_identities,
    )
    try:
        assert SKILL_NAME not in _tool_names(gateway)
    finally:
        gateway.close()


def test_portable_core_has_no_finos_api_database_or_path_dependency(tmp_path: Path) -> None:
    root = tmp_path / "skills"
    _write_skill(root, "portable/core")
    scoped_root = ScopedSkillRoot(scope=SkillScope.USER, root=str(root), namespace="private")
    core = LocalSkillCatalog((scoped_root,)).read(SKILL_NAME).content.lower()
    gateway = _gateway(tmp_path / "workspace", scoped_root)

    try:
        assert all(marker not in core for marker in ("finos.", "postgres", "sqlite", "/users/"))
        assert not {name for name in _tool_names(gateway) if name.startswith("finos.")}
    finally:
        gateway.close()


def _gateway(workspace: Path, root: ScopedSkillRoot) -> LocalToolGateway:
    return LocalToolGateway(
        workspace,
        policy_profile=PolicyProfile.READ_ONLY,
        skill_roots=(root,),
    )


def _run_skill_read(
    workspace: Path,
    root: ScopedSkillRoot,
):
    model = ScriptedModelGateway(
        (
            ScriptedModelResponse(
                ModelCompletion(
                    assistant_message=_message("Read the portable guidance."),
                    tool_calls=(_call("skills.read", {"name": SKILL_NAME}),),
                )
            ),
            ScriptedModelResponse(ModelCompletion(assistant_message=_message("Review complete."))),
            ScriptedModelResponse(ModelCompletion(assistant_message=_message("Review complete."))),
        )
    )
    return run_local_harness(
        prompt="Perform a portable review.",
        title="Portable review",
        workspace_root=workspace,
        model_gateway=model,
        policy_profile=PolicyProfile.READ_ONLY,
        skill_roots=(root,),
    )


def _message(content: str) -> SessionMessage:
    return SessionMessage(
        message_id=new_message_id(),
        role=MessageRole.ASSISTANT,
        content=content,
        created_at=NOW,
    )


def _call(name: str, arguments: dict[str, object]) -> ToolCall:
    return ToolCall(
        tool_call_id=new_tool_call_id(),
        name=name,
        arguments=arguments,
        created_at=NOW,
    )


def _tool_names(gateway: LocalToolGateway) -> set[str]:
    return {tool.name for tool in gateway.model_tools}


def _identity_mapping(metadata: SkillMetadata) -> dict[str, object]:
    return metadata.component_identity().model_dump(mode="json")


def _write_skill(
    root: Path,
    relative: str,
    *,
    extra_frontmatter: str = "",
    body: str = "Use supplied attachments and already granted capabilities only.\n",
) -> Path:
    skill = root / relative
    skill.mkdir(parents=True)
    skill_file = skill / "SKILL.md"
    skill_file.write_text(
        "---\n"
        f"name: {SKILL_NAME}\n"
        "description: Portable review guidance.\n"
        f"version: {SKILL_VERSION}\n"
        f"{extra_frontmatter}"
        "---\n"
        f"{body}",
        encoding="utf-8",
    )
    return skill_file
