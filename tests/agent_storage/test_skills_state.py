from pathlib import Path

import pytest
from agent_core.domain.skills import SkillComponentIdentity
from agent_storage import SQLiteSkillsStateStore
from agent_tools.skills_scope import compute_skill_digest


def test_set_enabled_is_idempotent_upsert(tmp_path: Path) -> None:
    database = tmp_path / "skills-state.sqlite"
    store = SQLiteSkillsStateStore(database)
    store.set_enabled(name="evidence", scope="user", enabled=False, operator="op-1")

    reopened = SQLiteSkillsStateStore(database)
    state = reopened.get_state(name="evidence", scope="user")
    assert state is not None
    assert state.enabled is False
    assert state.operator == "op-1"

    store.set_enabled(name="evidence", scope="user", enabled=True, operator="op-2")
    state = store.get_state(name="evidence", scope="user")
    assert state is not None and state.enabled is True
    assert state.operator == "op-2"


def test_missing_state_means_enabled_with_empty_disabled(tmp_path: Path) -> None:
    store = SQLiteSkillsStateStore(tmp_path / "skills-state.sqlite")
    assert store.get_state(name="ghost", scope="user") is None
    assert store.disabled_components() == frozenset()
    assert store.list_states() == ()


def test_disabled_components_is_per_name_scope(tmp_path: Path) -> None:
    store = SQLiteSkillsStateStore(tmp_path / "skills-state.sqlite")
    store.set_enabled(name="evidence", scope="user", enabled=False, operator="op")
    store.set_enabled(name="review", scope="system", enabled=False, operator="op")
    store.set_enabled(name="planner", scope="user", enabled=True, operator="op")
    assert store.disabled_components() == frozenset(
        {("evidence", "user"), ("review", "system")}
    )
    assert {record.name for record in store.list_states()} == {
        "evidence",
        "review",
        "planner",
    }


def test_private_installation_is_owner_scoped_immutable_and_durable(tmp_path: Path) -> None:
    content = "---\nname: private-review\ndescription: review\nversion: 1.0.0\n---\nV1\n"
    identity = SkillComponentIdentity(
        name="private-review",
        version="1.0.0",
        digest=compute_skill_digest(
            b"---\nname: private-review\ndescription: review\nversion: 1.0.0\n---",
            b"\nV1\n",
        ),
        scope="user",
        namespace="owner-a",
        source="private-review",
    )
    store = SQLiteSkillsStateStore(tmp_path / "skills-state.sqlite")
    stored = store.install_component(
        identity=identity,
        files={"SKILL.md": content},
        owner="owner-a",
        operator="op",
    )
    assert stored.files["SKILL.md"] == content
    assert store.is_component_enabled(identity=identity, owner="owner-a") is False
    store.set_component_enabled(identity=identity, owner="owner-a", enabled=True, operator="op")
    assert SQLiteSkillsStateStore(tmp_path / "skills-state.sqlite").is_component_enabled(
        identity=identity, owner="owner-a"
    )

    changed = identity.model_copy(
        update={
            "digest": compute_skill_digest(
                b"---\nname: private-review\ndescription: review\nversion: 1.0.0\n---",
                b"\nV2\n",
            )
        }
    )
    with pytest.raises(ValueError, match="immutable"):
        store.install_component(
            identity=changed,
            files={"SKILL.md": content.replace("V1", "V2")},
            owner="owner-a",
            operator="op",
        )
    owner_b = identity.model_copy(update={"namespace": "owner-b"})
    store.install_component(
        identity=owner_b,
        files={"SKILL.md": content},
        owner="owner-b",
        operator="op",
    )
    assert store.is_component_enabled(identity=owner_b, owner="owner-b") is False
