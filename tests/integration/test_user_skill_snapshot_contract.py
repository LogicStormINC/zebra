from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import pytest
from agent_core.application import SessionBootstrapCommand, SessionBootstrapService
from agent_core.application.mock_model import ScriptedModelGateway, ScriptedModelResponse
from agent_core.application.workspace_projection import rebuild_workspace
from agent_core.domain.identifiers import new_message_id, new_tool_call_id
from agent_core.domain.messages import MessageRole, SessionMessage
from agent_core.domain.modeling import ModelCompletion
from agent_core.domain.tool_profiles import ToolProfile
from agent_core.domain.tools import ToolCall, ToolCallStatus
from agent_runtime import LocalToolGateway
from agent_security import PolicyProfile
from agent_storage import (
    SQLiteEventStore,
    SQLiteLeaseStore,
    SQLiteProjectionStore,
    SQLiteSkillsStateStore,
    SQLiteWorkspaceProjectionStore,
)
from agent_tools.skills_catalog import LocalSkillCatalog
from agent_tools.skills_scope import SkillCatalogError, build_scoped_skill_roots
from zebra_agent_config import ApiSettings, ModelSettings, ZebraAgentSettings
from zebra_agent_worker import (
    SessionClaimService,
    SessionExecutionService,
    SessionRecoveryService,
    SessionResumeService,
)
from zebra_agent_worker.execution import WorkerExecutionError

OWNER = "owner-a"
NAME = "private-review"


def test_private_exact_grant_requires_installed_snapshot_in_gateway(tmp_path: Path) -> None:
    private_root = tmp_path / "private"
    _write_skill(private_root / ".zebra-private" / OWNER / NAME, "V1")
    roots = build_scoped_skill_roots(user=(str(private_root),), owner=OWNER)
    identity = (
        LocalSkillCatalog(roots, inventory_only=True).read(NAME).metadata.component_identity()
    )

    with pytest.raises(SkillCatalogError, match="identity is unavailable"):
        LocalToolGateway(
            tmp_path / "workspace",
            policy_profile=PolicyProfile.READ_ONLY,
            skill_roots=roots,
            skills_state=SQLiteSkillsStateStore(tmp_path / "skills-state.sqlite"),
            granted_skill_component_identities=(identity,),
        )


def test_worker_rejects_uninstalled_private_exact_grant(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    private_root = tmp_path / "private"
    _write_skill(private_root / ".zebra-private" / OWNER / NAME, "V1")
    roots = build_scoped_skill_roots(user=(str(private_root),), owner=OWNER)
    identity = (
        LocalSkillCatalog(roots, inventory_only=True).read(NAME).metadata.component_identity()
    )
    database = tmp_path / "sessions.sqlite"
    session_id = _queue_worker_task(database, tmp_path / "workspace", identity)
    settings = _settings(database, private_root)
    monkeypatch.setattr(
        "zebra_agent_worker.execution.build_model_gateway",
        lambda _settings: ScriptedModelGateway(
            (
                ScriptedModelResponse(
                    completion=ModelCompletion(
                        assistant_message=SessionMessage(
                            message_id=new_message_id(),
                            role=MessageRole.ASSISTANT,
                            content="This must not run.",
                            created_at=datetime.now(UTC),
                        )
                    )
                ),
            )
        ),
    )

    with pytest.raises(
        WorkerExecutionError, match="granted skill component identity is unavailable"
    ):
        _execution_service(database, settings).execute_session(session_id, worker_id="worker-a")


def test_pinned_private_snapshot_reads_through_later_live_name_collision(tmp_path: Path) -> None:
    private_root = tmp_path / "private"
    system_root = tmp_path / "system"
    _write_skill(private_root / ".zebra-private" / OWNER / NAME, "V1")
    system_root.mkdir()
    roots = build_scoped_skill_roots(
        system=(str(system_root),), user=(str(private_root),), owner=OWNER
    )
    inventory = LocalSkillCatalog(roots, inventory_only=True)
    identity = inventory.read(NAME).metadata.component_identity()
    state = SQLiteSkillsStateStore(tmp_path / "skills-state.sqlite")
    state.install_component(
        identity=identity,
        files=inventory.package_files(NAME),
        owner=OWNER,
        operator="test",
    )
    state.set_component_enabled(identity=identity, owner=OWNER, enabled=True, operator="test")
    _write_skill(system_root / NAME, "SYSTEM")

    available, ambiguous, _ = LocalSkillCatalog(roots, skills_state=state).list()
    assert available == ()
    assert ambiguous == 1

    gateway = LocalToolGateway(
        tmp_path / "workspace",
        policy_profile=PolicyProfile.READ_ONLY,
        skill_roots=roots,
        skills_state=state,
        granted_skill_component_identities=(identity,),
    )
    try:
        result = gateway.execute(_call("skills.read", {"name": NAME}))
        assert result.status is ToolCallStatus.EXECUTED
        assert "V1" in result.output and "SYSTEM" not in result.output
        assert result.metadata["skill_component_identity"] == identity.model_dump(mode="json")
    finally:
        gateway.close()


def test_private_support_file_drift_changes_identity_and_preserves_snapshot(tmp_path: Path) -> None:
    private_root = tmp_path / "private"
    package = private_root / ".zebra-private" / OWNER / NAME
    _write_skill(package, "V1")
    guide = package / "references" / "guide.md"
    guide.parent.mkdir()
    guide.write_text("V1 guide\n", encoding="utf-8")
    roots = build_scoped_skill_roots(user=(str(private_root),), owner=OWNER)
    catalog = LocalSkillCatalog(roots, inventory_only=True)
    initial = catalog.read(NAME).metadata.component_identity()
    state = SQLiteSkillsStateStore(tmp_path / "skills-state.sqlite")
    state.install_component(
        identity=initial,
        files=catalog.package_files(NAME),
        owner=OWNER,
        operator="test",
    )
    state.set_component_enabled(identity=initial, owner=OWNER, enabled=True, operator="test")
    guide.write_text("V2 guide\n", encoding="utf-8")
    changed_catalog = LocalSkillCatalog(roots, inventory_only=True)
    changed = changed_catalog.read(NAME).metadata.component_identity()

    assert changed.digest != initial.digest
    with pytest.raises(ValueError, match="immutable"):
        state.install_component(
            identity=changed,
            files=changed_catalog.package_files(NAME),
            owner=OWNER,
            operator="test",
        )
    gateway = LocalToolGateway(
        tmp_path / "workspace",
        policy_profile=PolicyProfile.READ_ONLY,
        skill_roots=roots,
        skills_state=state,
        granted_skill_component_identities=(initial,),
    )
    try:
        result = gateway.execute(
            _call("skills.read", {"name": NAME, "file_path": "references/guide.md"})
        )
        assert result.status is ToolCallStatus.EXECUTED
        assert result.output.endswith("V1 guide\n")
        assert result.metadata["skill_component_identity"] == initial.model_dump(mode="json")
    finally:
        gateway.close()


def _execution_service(database: Path, settings: ZebraAgentSettings) -> SessionExecutionService:
    claim_service = SessionClaimService(
        SQLiteLeaseStore(database),
        SessionRecoveryService(
            SQLiteEventStore(database),
            SQLiteProjectionStore(database),
            SQLiteWorkspaceProjectionStore(database),
        ),
    )
    return SessionExecutionService(
        database_path=database,
        claim_service=claim_service,
        resume_service=SessionResumeService(claim_service),
        settings=settings,
    )


def _queue_worker_task(database: Path, workspace: Path, identity) -> object:
    bootstrap = SessionBootstrapService().build(
        SessionBootstrapCommand(
            title="Private exact grant",
            user_input="Use the pinned Skill.",
            workspace_root=workspace.resolve(),
            policy_profile=PolicyProfile.READ_ONLY.value,
            tool_profile=ToolProfile.GENERAL,
            skill_components=(identity.name,),
            skill_component_identities=(identity,),
        )
    )
    events = SQLiteEventStore(database)
    for event in bootstrap.events:
        events.append(event)
    SQLiteProjectionStore(database).save_session(bootstrap.session)
    SQLiteWorkspaceProjectionStore(database).save_workspace(rebuild_workspace(list(bootstrap.events)))
    return bootstrap.session.session_id


def _settings(database: Path, private_root: Path) -> ZebraAgentSettings:
    return ZebraAgentSettings(
        profile="test",
        database_url=str(database),
        api=ApiSettings(auth_token=None),
        model=ModelSettings(
            provider="test",
            api_key_env="TEST_API_KEY",
            base_url="https://example.test",
            model="test-model",
        ),
        skill_roots=(str(private_root),),
        skills_state_path=str(database.with_name("skills-state.sqlite")),
    )


def _write_skill(directory: Path, marker: str) -> None:
    directory.mkdir(parents=True)
    (directory / "SKILL.md").write_text(
        "---\n"
        f"name: {NAME}\n"
        "description: Private review guidance.\n"
        "version: 1.0.0\n"
        "---\n"
        f"{marker}\n",
        encoding="utf-8",
    )


def _call(name: str, arguments: dict[str, object]) -> ToolCall:
    return ToolCall(
        tool_call_id=new_tool_call_id(),
        name=name,
        arguments=arguments,
        created_at=datetime.now(UTC),
    )
