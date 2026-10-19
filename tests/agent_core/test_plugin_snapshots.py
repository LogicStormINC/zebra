"""Compact provenance preserves old identities and exact admitted origins."""

import pytest
from agent_core.domain.execution_authority_support import digest
from agent_core.domain.extension_snapshots import ExtensionSnapshot
from agent_core.domain.plugin_snapshots import ExtensionSelection, PluginSnapshot

from tests.agent_storage.test_postgres_plugin_installations import SCOPE, _record


def test_legacy_digest_and_serialization_remain_identical() -> None:
    old = {
        "scope": SCOPE.model_dump(mode="json"),
        "session_id": "session-a",
        "turn_id": "turn-a",
        "skills": [],
        "mcp": [],
    }
    snapshot = ExtensionSnapshot.model_validate(old)
    assert snapshot.model_dump(mode="json") == old
    assert snapshot.digest == digest(old)


def test_provenance_requires_exact_component_coverage_and_changes_digest() -> None:
    from agent_core.domain.extension_snapshots import McpSnapshotEntry

    record = _record().model_copy(update={"enabled": True})
    entry = McpSnapshotEntry(
        connection=record.bindings[0].connection, catalog_digest=record.bindings[0].catalog_digest
    )
    ordinary = ExtensionSnapshot(
        scope=SCOPE, session_id="session-a", turn_id="turn-a", mcp=(entry,)
    )
    pin = PluginSnapshot.from_installation(record)
    admitted = ExtensionSnapshot(**ordinary.model_dump(), plugins=(pin,))
    assert admitted.digest != ordinary.digest
    assert "canonical_manifest" not in str(admitted.model_dump())
    with pytest.raises(ValueError, match="cover"):
        ExtensionSnapshot(scope=SCOPE, session_id="session-a", turn_id="turn-a", plugins=(pin,))
    with pytest.raises(ValueError, match="source"):
        ExtensionSnapshot(**ordinary.model_dump(), direct_mcp=("unadmitted",))
    assert ExtensionSelection().plugins == ()
    with pytest.raises(ValueError):
        ExtensionSelection.model_validate(
            {"plugins": [{"installation_id": "plugin-a", "revision": 1}], "scope": SCOPE}
        )


def test_serializer_allows_partial_dump_without_provenance_keys() -> None:
    snapshot = ExtensionSnapshot(scope=SCOPE, session_id="session-a", turn_id="turn-a")
    assert snapshot.model_dump(include={"session_id"}) == {"session_id": "session-a"}
    assert "plugins" not in snapshot.model_dump(exclude={"plugins"})
