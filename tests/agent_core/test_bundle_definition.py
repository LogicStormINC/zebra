"""Frozen native Bundle binding, independent of legacy Definition hashes."""

from datetime import UTC, datetime
from uuid import UUID, uuid4

import pytest
from agent_core.contracts.task_prepared import TaskPreparedPayload
from agent_core.domain.agent_definition_snapshots import AgentDefinitionSnapshot, BindingPurpose
from agent_core.domain.agent_definitions import AgentDefinitionVersion
from agent_core.domain.bundle_definition import (
    BundleDefinitionSnapshot,
    BundleDefinitionVersion,
    canonical_bundle_snapshot_digest,
    parse_definition_snapshot,
    parse_definition_version,
    snapshot_from_version,
)
from agent_core.domain.identifiers import AgentDefinitionId, AgentDefinitionVersionId
from agent_core.domain.runtime_assembly import (
    TEXT_OUTPUT_SCHEMA_DIGEST,
    RuntimeAssembly,
    canonical_provider_profile_digest,
)
from agent_core.domain.runtime_bundle_json import json_digest

from tests.agent_core.test_runtime_bundle import valid_payload


def assembly_payload():
    profile = {
        "provider": "openai-compatible",
        "base_url": "https://models.example/v1",
        "api_key_env": "MODEL_API_KEY",
        "models": ["example/model-1"],
        "max_context_window_tokens": 1_048_576,
        "max_output_tokens": 8192,
    }
    profile["pin"] = {
        "kind": "provider-profile",
        "id": "providers/example",
        "version": "1.0.0",
        "digest": json_digest(profile),
    }
    bundle = valid_payload()
    manifest = bundle["manifest"]
    model = manifest["domains"]["model"]["parameters"]
    old_provider = model["provider_profile"]
    model["provider_profile"] = profile["pin"]
    output = manifest["domains"]["instructions"]["parameters"]["output_schema"]
    old_output = dict(output)
    output["digest"] = TEXT_OUTPUT_SCHEMA_DIGEST
    manifest["lock"] = sorted(
        [
            profile["pin"] if pin == old_provider else output if pin == old_output else pin
            for pin in manifest["lock"]
        ],
        key=lambda pin: (pin["kind"], pin["id"], pin["version"]),
    )
    bundle["bundle_digest"] = json_digest(manifest)
    return {"bundle": bundle, "provider_profile": profile}


def test_assembly_is_immutable_exact_roundtrip():
    assembly = RuntimeAssembly.model_validate(assembly_payload())
    assert RuntimeAssembly.model_validate_json(assembly.model_dump_json()) == assembly
    assert assembly.assembly_digest == json_digest(assembly.model_dump(mode="json"))


NOW = datetime(2026, 10, 21, tzinfo=UTC)
REFERENCES = {
    name: name.replace("_ref", "").replace("_", "-") + "/native@1"
    for name in (
        "model_policy_ref",
        "tool_profile_ref",
        "memory_policy_ref",
        "security_policy_ref",
        "evaluation_profile_ref",
        "runtime_profile_ref",
    )
}


def bundle_version(**changes):
    payload = dict(
        version_id=AgentDefinitionVersionId(uuid4()),
        definition_id=AgentDefinitionId(uuid4()),
        authority_issuer="https://business.example",
        namespace_id="tenant/example",
        version=1,
        created_at=NOW,
        skill_snapshot_digest="a" * 64,
        **REFERENCES,
        runtime_assembly=RuntimeAssembly.model_validate(assembly_payload()),
    )
    return BundleDefinitionVersion(**{**payload, **changes})


def test_version_snapshot_task_recovery_retains_whole_assembly():
    version = bundle_version()
    assert parse_definition_version(version.model_dump(mode="json")) == version
    snapshot = snapshot_from_version(version=version, resolved_at=NOW)
    assert isinstance(snapshot, BundleDefinitionSnapshot)
    prepared = TaskPreparedPayload(title="task", user_input="test", definition_snapshot=snapshot)
    recovered = TaskPreparedPayload.model_validate_json(prepared.model_dump_json())
    assert recovered.definition_snapshot == snapshot
    assert isinstance(recovered.definition_snapshot, BundleDefinitionSnapshot)
    assert recovered.definition_snapshot.bound_version == version


@pytest.mark.parametrize(
    "change",
    [
        {"base_url": "http://models.example"},
        {"base_url": "https://u:p@models.example"},
        {"base_url": "https://models.example?key=x"},
        {"base_url": "https://models.example#x"},
        {"base_url": "https://models.example\n/v1"},
        {"base_url": "https://models.example:0"},
        {"api_key_env": "actual-secret-value"},
        {"provider": "other"},
        {"models": []},
        {"max_context_window_tokens": True},
        {"extra": "field"},
    ],
)
def test_provider_public_content_validation_survives_recomputed_digest(change):
    payload = assembly_payload()
    profile = payload["provider_profile"]
    profile.update(change)
    profile["pin"]["digest"] = canonical_provider_profile_digest(profile)
    with pytest.raises(ValueError):
        RuntimeAssembly.model_validate(payload)


@pytest.mark.parametrize(
    "field,value",
    [
        ("model", "other/model"),
        ("thinking", "enabled"),
        ("max_output_tokens", 8193),
    ],
)
def test_assembly_enforces_approval_after_bundle_is_resealed(field, value):
    payload = assembly_payload()
    payload["bundle"]["manifest"]["domains"]["model"]["parameters"][field] = value
    payload["bundle"]["bundle_digest"] = json_digest(payload["bundle"]["manifest"])
    with pytest.raises(ValueError):
        RuntimeAssembly.model_validate(payload)


def test_provider_digest_and_copied_nested_instances_fail_closed():
    payload = assembly_payload()
    payload["provider_profile"]["base_url"] = "https://different.example"
    with pytest.raises(ValueError, match="digest mismatch"):
        RuntimeAssembly.model_validate(payload)
    assembly = RuntimeAssembly.model_validate(assembly_payload())
    unsafe = assembly.model_copy(
        update={
            "provider_profile": assembly.provider_profile.model_copy(
                update={"base_url": "http://bad"}
            )
        }
    )
    with pytest.raises(ValueError):
        RuntimeAssembly.model_validate(unsafe)
    version = bundle_version()
    with pytest.raises(ValueError):
        parse_definition_version(version.model_copy(update={"namespace_id": "foreign"}))


def test_snapshot_cannot_diverge_from_embedded_version_even_with_new_digest():
    snapshot = snapshot_from_version(version=bundle_version(), resolved_at=NOW)
    changed = snapshot.model_copy(update={"model_policy_ref": "model/other@1"})
    changed = changed.model_copy(
        update={"snapshot_digest": canonical_bundle_snapshot_digest(changed)}
    )
    with pytest.raises(ValueError, match="differs"):
        parse_definition_snapshot(changed)
    changed_version = snapshot.bound_version.model_copy(update={"definition_digest": "0" * 64})
    with pytest.raises(ValueError):
        parse_definition_snapshot(snapshot.model_copy(update={"bound_version": changed_version}))


@pytest.mark.parametrize(
    "parser,key",
    [
        (parse_definition_version, "schema_version"),
        (parse_definition_snapshot, "snapshot_schema_version"),
    ],
)
def test_unknown_schema_dispatch_fails_closed(parser, key):
    with pytest.raises(ValueError, match="unsupported"):
        parser({key: "unknown/99"})


def test_v1_exact_digest_and_snapshot_bytes_are_unchanged():
    version = AgentDefinitionVersion(
        version_id=AgentDefinitionVersionId(UUID(int=1)),
        definition_id=AgentDefinitionId(UUID(int=2)),
        authority_issuer="https://business.example",
        namespace_id="tenant/example",
        version=1,
        created_at=NOW,
        skill_snapshot_digest="a" * 64,
        **REFERENCES,
    )
    snapshot = AgentDefinitionSnapshot.from_version(version=version, resolved_at=NOW)
    assert parse_definition_version(version.model_dump()) == version
    assert (
        parse_definition_snapshot(snapshot.model_dump()).model_dump_json()
        == snapshot.model_dump_json()
    )
    assert (
        version.definition_digest
        == "8c31e2322983981e4707887febe8ad7fc1e3b2efec6d70f7dbb42d8a63cf063a"
    )


def test_assembly_context_reserves_and_output_format_fail_before_execution():
    payload = assembly_payload()
    parameters = payload["bundle"]["manifest"]["domains"]["model"]["parameters"]
    parameters["context_window_tokens"] = 6001
    payload["bundle"]["bundle_digest"] = json_digest(payload["bundle"]["manifest"])
    with pytest.raises(ValueError, match="no room for input"):
        RuntimeAssembly.model_validate(payload)
    payload = assembly_payload()
    manifest = payload["bundle"]["manifest"]
    output = manifest["domains"]["instructions"]["parameters"]["output_schema"]
    old_digest = output["digest"]
    output["digest"] = json_digest(
        {"format": "json", "schema_version": "cloud-agent.text-output/1"}
    )
    for pin in manifest["lock"]:
        if pin["digest"] == old_digest:
            pin["digest"] = output["digest"]
    payload["bundle"]["bundle_digest"] = json_digest(manifest)
    with pytest.raises(ValueError, match="text output"):
        RuntimeAssembly.model_validate(payload)


def test_version_and_snapshot_scope_purpose_and_unknown_null_schemas():
    with pytest.raises(ValueError, match="scope"):
        bundle_version(namespace_id="foreign")
    version = bundle_version()
    snapshot = snapshot_from_version(version=version, resolved_at=NOW)
    for update in (
        {"binding_purpose": "production"},
        {"release_revision": 1},
        {"namespace_id": "foreign"},
    ):
        # A recomputed outer digest must not bypass inner constraints.
        values = {**snapshot.model_dump(), **update}
        values["binding_purpose"] = BindingPurpose(values["binding_purpose"])
        values["bound_version"] = version
        unsafe = BundleDefinitionSnapshot.model_construct(**values)
        values["snapshot_digest"] = canonical_bundle_snapshot_digest(unsafe)
        with pytest.raises(ValueError):
            parse_definition_snapshot(values)
    for parser, schema_field in (
        (parse_definition_version, "schema_version"),
        (parse_definition_snapshot, "snapshot_schema_version"),
    ):
        with pytest.raises(ValueError):
            parser(None)
        with pytest.raises(ValueError):
            parser({schema_field: None})


def test_workspace_projection_and_memory_replay_retain_v2_scope():
    from agent_core.application.memory_scopes import governed_memory_scope_from_events
    from agent_core.application.workspace_projection import rebuild_workspace
    from agent_core.domain.events import EventActor, EventType, SessionEvent
    from agent_core.domain.identifiers import new_session_id
    from agent_core.domain.workspaces import WorkspaceProjection

    version = bundle_version()
    snapshot = snapshot_from_version(version=version, resolved_at=NOW)
    event = SessionEvent.create(
        session_id=new_session_id(),
        sequence=1,
        event_type=EventType.TASK_PREPARED,
        actor=EventActor.HARNESS,
        created_at=NOW,
        payload={
            "title": "task",
            "user_input": "test",
            "workspace_root": "/tmp/bundle",
            "definition_snapshot": snapshot.model_dump(mode="json"),
        },
    )
    workspace = rebuild_workspace([event])
    assert workspace.definition_snapshot == snapshot
    assert WorkspaceProjection.model_validate_json(workspace.model_dump_json()) == workspace
    scope = governed_memory_scope_from_events([event], fallback_repo_id="repo")
    assert scope is not None and scope.definition_id == version.definition_id
    assert (
        scope.authority_issuer == version.authority_issuer
        and scope.namespace_id == version.namespace_id
    )
