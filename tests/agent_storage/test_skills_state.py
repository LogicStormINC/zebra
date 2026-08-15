import sqlite3
from pathlib import Path
from threading import Barrier, Thread

import pytest
from agent_core.domain.skills import SkillComponentIdentity, compute_private_skill_package_digest
from agent_storage import SQLiteSkillsStateStore
from agent_storage.database import SQLiteDatabase


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
        digest=compute_private_skill_package_digest({"SKILL.md": content}),
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
            "digest": compute_private_skill_package_digest(
                {"SKILL.md": content.replace("V1", "V2")}
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


def test_concurrent_identical_private_install_is_idempotent(tmp_path: Path, monkeypatch) -> None:
    database = tmp_path / "skills-state.sqlite"
    content = "---\nname: private-review\ndescription: review\nversion: 1.0.0\n---\nV1\n"
    identity = SkillComponentIdentity(
        name="private-review",
        version="1.0.0",
        digest=compute_private_skill_package_digest({"SKILL.md": content}),
        scope="user",
        namespace="owner-a",
        source="private-review",
    )
    stores = (SQLiteSkillsStateStore(database), SQLiteSkillsStateStore(database))
    original_connect = SQLiteDatabase.connect
    selected = Barrier(2)

    class CoordinatedConnection:
        def __init__(self, connection: sqlite3.Connection) -> None:
            self._connection = connection
            self._inserted_installation = False

        def __enter__(self):
            self._connection.__enter__()
            return self

        def __exit__(self, *args):
            return self._connection.__exit__(*args)

        def execute(self, statement: str, *args):
            if "skill_installations" in statement and "INSERT" in statement:
                self._inserted_installation = True
            result = self._connection.execute(statement, *args)
            if "SELECT * FROM skill_installations" in statement and not self._inserted_installation:
                selected.wait(timeout=5)
            return result

        def __getattr__(self, name: str):
            return getattr(self._connection, name)

    monkeypatch.setattr(
        SQLiteDatabase,
        "connect",
        lambda database: CoordinatedConnection(original_connect(database)),
    )
    records: list[object] = []
    failures: list[BaseException] = []

    def install(store: SQLiteSkillsStateStore) -> None:
        try:
            records.append(
                store.install_component(
                    identity=identity,
                    files={"SKILL.md": content},
                    owner="owner-a",
                    operator="op",
                )
            )
        except BaseException as error:
            failures.append(error)

    threads = tuple(Thread(target=install, args=(store,)) for store in stores)
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    assert failures == []
    assert len(records) == 2
    with sqlite3.connect(database) as connection:
        assert connection.execute("SELECT COUNT(*) FROM skill_installations").fetchone()[0] == 1
