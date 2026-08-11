from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import pytest
from agent_core.application.mock_model import ScriptedModelGateway, ScriptedModelResponse
from agent_core.domain.identifiers import new_message_id
from agent_core.domain.messages import MessageRole, SessionMessage
from agent_core.domain.modeling import ModelCompletion
from agent_core.domain.tools import ToolCall, ToolCallStatus
from agent_runtime import LocalToolGateway
from agent_security import LocalPolicyEngine, PolicyProfile
from agent_storage import SQLiteEventStore, SQLiteSkillsStateStore
from agent_tools.skills_catalog import LocalSkillCatalog
from agent_tools.skills_scope import ScopedSkillRoot, SkillScope, build_scoped_skill_roots
from zebra_agent_api.app import create_app
from zebra_agent_config import ApiSettings, ModelSettings, ZebraAgentSettings

OWNER_A = "owner-a"
OWNER_B = "owner-b"
SKILL_NAME = "private-review"


def test_omitted_skill_components_grant_nothing_even_when_enabled(tmp_path: Path) -> None:
    root = tmp_path / "skills"
    skill_file = _write_skill(
        root / ".zebra-private" / OWNER_A / SKILL_NAME, version="1.0.0", marker="V1"
    )
    skill_file.write_text(
        skill_file.read_text(encoding="utf-8").replace(
            "description: Private review guidance.",
            "description: Private review guidance.\nrequested_capability: core:read",
        ),
        encoding="utf-8",
    )
    database = tmp_path / "sessions.sqlite"
    app = create_app(database, settings=_settings(database, root))
    assert app.install_skill(SKILL_NAME, {"owner": OWNER_A}).status_code == 200
    assert app.enable_skill(SKILL_NAME, {"owner": OWNER_A}).status_code == 200

    response = app.create_session(
        {
            "prompt": "Use the ordinary runtime.",
            "workspace": str(tmp_path),
            "execute": False,
            "skill_owner": OWNER_A,
        }
    )

    assert response.status_code == 201
    events = SQLiteEventStore(database).list_for_session(response.body["session_id"])
    prepared = next(event for event in events if event.event_type.value == "task_prepared")
    assert prepared.payload["skill_components"] == []
    assert prepared.payload["skill_component_identities"] == []
    rejected = app.create_session(
        {
            "prompt": "Use the legacy namespace as an owner.",
            "workspace": str(tmp_path),
            "execute": False,
            "skill_owner": "user",
        }
    )
    assert rejected.status_code == 400


def test_private_owner_isolation_and_system_name_collision_fail_closed(tmp_path: Path) -> None:
    system_root = tmp_path / "system"
    private_root = tmp_path / "private"
    _write_skill(system_root / SKILL_NAME, version="1.0.0", marker="SYSTEM")
    _write_skill(
        private_root / ".zebra-private" / OWNER_A / SKILL_NAME, version="1.0.0", marker="A"
    )
    _write_skill(
        private_root / ".zebra-private" / OWNER_B / SKILL_NAME, version="1.0.0", marker="B"
    )

    owner_a_roots = build_scoped_skill_roots(
        system=(str(system_root),), user=(str(private_root),), owner=OWNER_A
    )
    owner_b_roots = build_scoped_skill_roots(user=(str(private_root),), owner=OWNER_B)

    owner_a, ambiguous, _ = LocalSkillCatalog(owner_a_roots, inventory_only=True).list()
    owner_b, _, _ = LocalSkillCatalog(owner_b_roots, inventory_only=True).list()

    assert owner_a == ()
    assert ambiguous == 1
    assert [(skill.namespace, skill.owner) for skill in owner_b] == [(OWNER_B, OWNER_B)]


def test_private_container_is_hidden_from_ownerless_catalog(tmp_path: Path) -> None:
    private_root = tmp_path / "private"
    _write_skill(
        private_root / ".zebra-private" / OWNER_A / SKILL_NAME,
        version="1.0.0",
        marker="A",
    )

    available, ambiguous, _ = LocalSkillCatalog(
        build_scoped_skill_roots(user=(str(private_root),)), inventory_only=True
    ).list()

    assert available == ()
    assert ambiguous == 0


def test_private_install_is_immutable_and_never_executes_package_code(tmp_path: Path) -> None:
    private_root = tmp_path / "private"
    skill_file = _write_skill(
        private_root / ".zebra-private" / OWNER_A / SKILL_NAME, version="1.0.0", marker="V1"
    )
    script_marker = tmp_path / "executed"
    scripts = skill_file.parent / "scripts"
    scripts.mkdir()
    (scripts / "must-not-run.py").write_text(
        f"from pathlib import Path\nPath({str(script_marker)!r}).write_text('bad')\n",
        encoding="utf-8",
    )
    root = ScopedSkillRoot(
        scope=SkillScope.USER,
        root=str(private_root / ".zebra-private" / OWNER_A),
        namespace=OWNER_A,
        owner=OWNER_A,
    )
    catalog = LocalSkillCatalog((root,), inventory_only=True)
    initial = catalog.read(SKILL_NAME)
    state = SQLiteSkillsStateStore(tmp_path / "skills-state.sqlite")

    state.install_component(
        identity=initial.metadata.component_identity(),
        files=catalog.package_files(SKILL_NAME),
        owner=OWNER_A,
        operator="test",
    )
    assert not script_marker.exists()

    skill_file.write_text(
        skill_file.read_text(encoding="utf-8").replace("V1", "V2"), encoding="utf-8"
    )
    changed = LocalSkillCatalog((root,), inventory_only=True).read(SKILL_NAME)
    with pytest.raises(ValueError, match="immutable"):
        state.install_component(
            identity=changed.metadata.component_identity(),
            files=LocalSkillCatalog((root,), inventory_only=True).package_files(SKILL_NAME),
            owner=OWNER_A,
            operator="test",
        )
    skill_file.write_text(
        skill_file.read_text(encoding="utf-8").replace("version: 1.0.0", "version: 2.0.0"),
        encoding="utf-8",
    )
    v2 = LocalSkillCatalog(
        (root,), inventory_only=True
    ).read(SKILL_NAME).metadata.component_identity()
    state.install_component(
        identity=v2,
        files=LocalSkillCatalog((root,), inventory_only=True).package_files(SKILL_NAME),
        owner=OWNER_A,
        operator="test",
    )
    assert state.installed_component(identity=initial.metadata.component_identity(), owner=OWNER_A)
    assert state.installed_component(identity=v2, owner=OWNER_A)


def test_disable_blocks_new_grants_but_pinned_task_reads_its_installed_v1(tmp_path: Path) -> None:
    private_root = tmp_path / "private"
    skill_file = _write_skill(
        private_root / ".zebra-private" / OWNER_A / SKILL_NAME, version="1.0.0", marker="V1"
    )
    root = ScopedSkillRoot(
        scope=SkillScope.USER,
        root=str(private_root / ".zebra-private" / OWNER_A),
        namespace=OWNER_A,
        owner=OWNER_A,
    )
    catalog = LocalSkillCatalog((root,), inventory_only=True)
    initial = catalog.read(SKILL_NAME)
    identity = initial.metadata.component_identity()
    state = SQLiteSkillsStateStore(tmp_path / "skills-state.sqlite")
    state.install_component(
        identity=identity,
        files=catalog.package_files(SKILL_NAME),
        owner=OWNER_A,
        operator="test",
    )
    state.set_component_enabled(identity=identity, owner=OWNER_A, enabled=True, operator="test")
    state.set_component_enabled(identity=identity, owner=OWNER_A, enabled=False, operator="test")
    skill_file.write_text(
        skill_file.read_text(encoding="utf-8").replace("V1", "V2"), encoding="utf-8"
    )

    gateway = LocalToolGateway(
        tmp_path / "workspace",
        policy_profile=PolicyProfile.READ_ONLY,
        skill_roots=(root,),
        skills_state=state,
        granted_skill_component_identities=(identity,),
    )
    try:
        result = gateway.execute(_call("skills.read", {"name": SKILL_NAME}))
        assert result.status is ToolCallStatus.EXECUTED
        assert "V1" in result.output
        assert "V2" not in result.output
        assert result.metadata["skill_component_identity"] == identity.model_dump(mode="json")
    finally:
        gateway.close()


def test_inline_private_grant_runs_from_the_installed_snapshot(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    private_root = tmp_path / "private"
    _write_skill(
        private_root / ".zebra-private" / OWNER_A / SKILL_NAME, version="1.0.0", marker="V1"
    )
    database = tmp_path / "sessions.sqlite"
    app = create_app(database, settings=_settings(database, private_root))
    assert app.install_skill(SKILL_NAME, {"owner": OWNER_A}).status_code == 200
    assert app.enable_skill(SKILL_NAME, {"owner": OWNER_A}).status_code == 200
    monkeypatch.setattr(
        "zebra_agent_api.app.build_model_gateway",
        lambda _settings: ScriptedModelGateway(
            (
                ScriptedModelResponse(
                    completion=ModelCompletion(
                        assistant_message=SessionMessage(
                            message_id=new_message_id(),
                            role=MessageRole.ASSISTANT,
                            content="Private skill ran.",
                            created_at=datetime.now(UTC),
                        )
                    )
                ),
            )
        ),
    )

    response = app.create_session(
        {
            "prompt": "Run the private skill now.",
            "workspace": str(tmp_path),
            "execute": True,
            "skill_owner": OWNER_A,
            "skill_components": [SKILL_NAME],
        }
    )

    assert response.status_code == 201
    assert response.body["status"] == "completed"


def test_worker_resumes_a_disabled_private_grant_from_its_installed_snapshot(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    private_root = tmp_path / "private"
    skill_file = _write_skill(
        private_root / ".zebra-private" / OWNER_A / SKILL_NAME, version="1.0.0", marker="V1"
    )
    database = tmp_path / "sessions.sqlite"
    app = create_app(database, settings=_settings(database, private_root))
    assert app.install_skill(SKILL_NAME, {"owner": OWNER_A}).status_code == 200
    assert app.enable_skill(SKILL_NAME, {"owner": OWNER_A}).status_code == 200
    queued = app.create_session(
        {
            "prompt": "Resume the pinned private skill.",
            "workspace": str(tmp_path),
            "execute": False,
            "skill_owner": OWNER_A,
            "skill_components": [SKILL_NAME],
        }
    )
    assert queued.status_code == 201
    assert app.disable_skill(SKILL_NAME, {"owner": OWNER_A}).status_code == 200
    blocked = app.create_session(
        {
            "prompt": "Grant the disabled private skill.",
            "workspace": str(tmp_path),
            "execute": False,
            "skill_owner": OWNER_A,
            "skill_components": [SKILL_NAME],
        }
    )
    assert blocked.status_code == 400
    skill_file.write_text(
        skill_file.read_text(encoding="utf-8").replace("V1", "V2"), encoding="utf-8"
    )
    monkeypatch.setattr(
        "zebra_agent_worker.execution.build_model_gateway",
        lambda _settings: ScriptedModelGateway(
            (
                ScriptedModelResponse(
                    completion=ModelCompletion(
                        assistant_message=SessionMessage(
                            message_id=new_message_id(),
                            role=MessageRole.ASSISTANT,
                            content="Pinned skill resumed.",
                            created_at=datetime.now(UTC),
                        )
                    )
                ),
            )
        ),
    )

    resumed = app.resume_session(queued.body["session_id"], {"worker_id": "worker-a"})

    assert resumed.status_code == 200
    assert resumed.body["status"] == "completed"


def test_system_and_private_skills_share_policy_and_persistence_boundaries(tmp_path: Path) -> None:
    system_root = tmp_path / "system"
    private_root = tmp_path / "private"
    _write_skill(system_root / SKILL_NAME, version="1.0.0", marker="SYSTEM")
    _write_skill(
        private_root / ".zebra-private" / OWNER_A / SKILL_NAME, version="1.0.0", marker="PRIVATE"
    )
    system = ScopedSkillRoot(scope=SkillScope.SYSTEM, root=str(system_root), namespace="system")
    private = ScopedSkillRoot(
        scope=SkillScope.USER,
        root=str(private_root / ".zebra-private" / OWNER_A),
        namespace=OWNER_A,
        owner=OWNER_A,
    )
    state = SQLiteSkillsStateStore(tmp_path / "skills-state.sqlite")
    private_catalog = LocalSkillCatalog((private,), inventory_only=True)
    private_identity = private_catalog.read(SKILL_NAME).metadata.component_identity()
    state.install_component(
        identity=private_identity,
        files=private_catalog.package_files(SKILL_NAME),
        owner=OWNER_A,
        operator="test",
    )
    state.set_component_enabled(
        identity=private_identity, owner=OWNER_A, enabled=True, operator="test"
    )
    system_gateway = LocalToolGateway(
        tmp_path / "system-workspace",
        policy_profile=PolicyProfile.READ_ONLY,
        skill_roots=(system,),
        granted_skill_component_identities=(
            LocalSkillCatalog((system,)).read(SKILL_NAME).metadata.component_identity(),
        ),
    )
    private_gateway = LocalToolGateway(
        tmp_path / "private-workspace",
        policy_profile=PolicyProfile.READ_ONLY,
        skill_roots=(private,),
        skills_state=state,
        granted_skill_component_identities=(private_identity,),
    )
    try:
        assert {tool.name for tool in system_gateway.model_tools} == {
            tool.name for tool in private_gateway.model_tools
        }
        policy = LocalPolicyEngine(profile=PolicyProfile.READ_ONLY)
        assert (
            policy.evaluate_tool_call(_call("patch.apply", {"patch": "x"})).decision.value
            == "deny"
        )
        candidate = private_gateway.execute(
            _call(
                "artifact.output_contract.emit",
                {
                    "output_contract": {
                        "contract_id": "portable.review",
                        "contract_version": "1",
                        "structured_payload": {"summary": "candidate"},
                        "source_refs": ["attachment://input"],
                    }
                },
            )
        )
        assert candidate.status is ToolCallStatus.EXECUTED
        assert (
            private_gateway.execute(_call("host.review.save", {})).status
            is ToolCallStatus.FAILED
        )
    finally:
        system_gateway.close()
        private_gateway.close()


def _settings(database: Path, skills: Path) -> ZebraAgentSettings:
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
        skill_roots=(str(skills),),
        skills_state_path=str(database.with_name("skills-state.sqlite")),
    )


def _write_skill(directory: Path, *, version: str, marker: str) -> Path:
    directory.mkdir(parents=True)
    skill_file = directory / "SKILL.md"
    skill_file.write_text(
        "---\n"
        f"name: {SKILL_NAME}\n"
        "description: Private review guidance.\n"
        f"version: {version}\n"
        "---\n"
        f"{marker}\n",
        encoding="utf-8",
    )
    return skill_file


def _call(name: str, arguments: dict[str, object]) -> ToolCall:
    from agent_core.domain.identifiers import new_tool_call_id

    return ToolCall(
        tool_call_id=new_tool_call_id(),
        name=name,
        arguments=arguments,
        created_at=datetime.now(UTC),
    )
