from pathlib import Path

from agent_storage import SQLiteSkillsStateStore


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
