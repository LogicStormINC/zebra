"""Public admission pins the complete v3 snapshot; old v1/v2 bindings stay byte-compatible."""

from uuid import UUID

from agent_core.domain.agent_definition_snapshots import AgentDefinitionSnapshot
from agent_core.domain.agent_definitions import AgentDefinitionVersion
from agent_core.domain.bundle_definition import snapshot_from_version
from agent_core.domain.identifiers import AgentDefinitionId, AgentDefinitionVersionId
from zebra_agent_api.session_queue import _derive_binding

from tests.agent_core.test_bundle_definition import NOW, REFERENCES, bundle_version
from tests.agent_core.test_native_script_binding import assembly_and_config, version


def derive(snapshot):
    return _derive_binding(
        UUID(int=7), host_context=None, definition_snapshot=snapshot, deployment_namespace="local"
    )


def test_v3_admission_ceiling_pins_full_snapshot_not_version(tmp_path):
    assembly, _, _ = assembly_and_config(tmp_path)
    snapshot = snapshot_from_version(version=version(assembly), resolved_at=NOW)
    assert snapshot.snapshot_schema_version == "agent-definition-snapshot/3"
    assert snapshot.definition_digest != snapshot.snapshot_digest
    binding = derive(snapshot)
    assert binding.agent_capability_ceiling.definition_snapshot_digest == snapshot.snapshot_digest


def test_legacy_binding_rules_and_absent_snapshot_unchanged():
    legacy = AgentDefinitionVersion(
        version_id=AgentDefinitionVersionId(UUID(int=1)),
        definition_id=AgentDefinitionId(UUID(int=2)),
        authority_issuer="https://business.example",
        namespace_id="tenant/example",
        version=1,
        created_at=NOW,
        skill_snapshot_digest="a" * 64,
        **REFERENCES,
    )
    for snapshot in [
        AgentDefinitionSnapshot.from_version(version=legacy, resolved_at=NOW),
        snapshot_from_version(version=bundle_version(), resolved_at=NOW),
    ]:
        assert (
            derive(snapshot).agent_capability_ceiling.definition_snapshot_digest
            == snapshot.definition_digest
        )
    assert derive(None).agent_capability_ceiling.definition_snapshot_digest == "0" * 64
