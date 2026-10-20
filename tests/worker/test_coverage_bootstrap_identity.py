"""Strict raw preparation and persisted manifest identity at cloud bootstrap."""

# ruff: noqa: F811 - imported pytest fixtures are consumed by parameter name

from dataclasses import replace

import pytest
from agent_core.domain.events import EventActor, EventType, SessionEvent
from agent_integrations.host_tools.contracts import HostToolManifest
from agent_storage.postgres import coverage as coverage_storage
from agent_storage.postgres.task_admission import save_task_binding
from zebra_agent_worker import coverage_bootstrap as module

from tests.worker.test_coverage_bootstrap import (
    cloud,  # noqa: F401
    component,  # noqa: F401
    counts,
    dsn,  # noqa: F401
    postgres_dsn,  # noqa: F401
)


@pytest.mark.parametrize("cloud", [True, "v2"], indirect=True)
def test_real_bootstrap_persists_verified_snapshot_source_ref(cloud):
    env = cloud
    result = module.bootstrap_cloud_coverage(**env.kwargs)
    assert (
        result.binding.snapshot.source_resource_ref
        == env.source.host.resource.resource_id
        == env.admission.source_resource.resource_id
    )
    event = next(
        event
        for event in env.events.list_for_session(env.session)
        if event.event_type == EventType.COVERAGE_MANIFEST_COMMITTED
    )
    assert (
        event.payload["binding"]["snapshot"]["source_resource_ref"]
        == env.admission.source_resource.resource_id
    )
    # A fresh bootstrap must preserve the same persisted run identity.
    assert module.bootstrap_cloud_coverage(**env.kwargs).binding == result.binding


def forge(prepared, target, storage):
    value = {
        "descriptor": prepared.descriptor,
        "record": prepared.records[0],
        "part": prepared.records[0].parts[0],
    }[target].model_copy()
    if storage == "copy":
        value = value.model_copy(update={"unknown": True})
    elif storage == "extras":
        object.__setattr__(value, "__pydantic_extra__", {"unknown": True})
    else:
        # A nested typed value must be reconstructed rather than dumped away.
        value = value.model_copy(
            update={
                "authority_revision"
                if target == "descriptor"
                else "parts"
                if target == "record"
                else "byte_length": prepared.descriptor.model_copy(update={"unknown": True}),
            }
        )
    if target == "descriptor":
        return replace(prepared, descriptor=value)
    record = (
        value
        if target == "record"
        else prepared.records[0].model_copy(
            update={
                "parts": (value,),
            }
        )
    )
    return replace(prepared, records=(record, *prepared.records[1:]))


@pytest.mark.parametrize("operation", ["create", "get"])
@pytest.mark.parametrize("target", ["descriptor", "record", "part"])
@pytest.mark.parametrize("storage", ["copy", "extras", "nested"])
def test_raw_source_fields_refused_before_publication(
    component, monkeypatch, operation, target, storage
):
    env = component
    original = getattr(env.source, operation)

    def corrupt(*args, **kwargs):
        return forge(original(*args, **kwargs), target, storage)

    monkeypatch.setattr(env.source, operation, corrupt)
    options = {"snapshot_id": "snapshot"} if operation == "get" else {}
    with pytest.raises(ValueError, match="unknown attributes"):
        module.bootstrap_cloud_coverage(**env.kwargs, **options)
    env.publisher.assert_not_called()
    env.store.bind.assert_not_called()


def other_manifest(manifest):
    payload = manifest.to_payload()
    payload.pop("manifestDigest")
    payload["tools"][0]["maxOutputBytes"] -= 1
    return HostToolManifest.from_payload(payload)


@pytest.mark.parametrize(
    "problem", ["missing", "zero", "different", "persisted_zero", "persisted_different"]
)
def test_manifest_must_match_persisted_task_before_host(component, problem):
    env = component
    if problem == "missing":
        env.source.host.manifest = None
    elif problem == "zero":
        env.source.host.manifest = replace(env.source.host.manifest, digest="0" * 64)
    elif problem == "different":
        env.source.host.manifest = other_manifest(env.source.host.manifest)
    else:
        env.task_binding = env.task_binding.model_copy(
            update={
                "host_capability": env.task_binding.host_capability.model_copy(
                    update={
                        "manifest_digest": ("0" if problem == "persisted_zero" else "f") * 64,
                    }
                ),
            }
        )
    with pytest.raises(ValueError, match="manifest"):
        module.bootstrap_cloud_coverage(**env.kwargs)
    assert not env.wire.calls
    env.publisher.assert_not_called()
    env.store.bind.assert_not_called()


def test_real_descriptor_extras_leave_no_publication_or_run(cloud, monkeypatch):
    before = counts(cloud)
    original = cloud.source.create

    def corrupt(*args, **kwargs):
        return forge(original(*args, **kwargs), "descriptor", "copy")

    monkeypatch.setattr(cloud.source, "create", corrupt)
    with pytest.raises(ValueError, match="unknown attributes"):
        module.bootstrap_cloud_coverage(**cloud.kwargs)
    assert counts(cloud) == before


def test_real_self_selected_manifest_cannot_call_host(cloud):
    before = counts(cloud)
    cloud.source.host.manifest = other_manifest(cloud.source.host.manifest)
    with pytest.raises(ValueError, match="persisted Task manifest"):
        module.bootstrap_cloud_coverage(**cloud.kwargs)
    assert not cloud.wire.calls and counts(cloud) == before


@pytest.mark.parametrize("change", ["admission_event", "binding_renewal"])
def test_real_final_bind_window_cannot_commit_raced_identity(cloud, monkeypatch, change):
    env = cloud
    original = coverage_storage.read_manifest
    before = counts(env)

    def read_then_race(*args):
        records = original(*args)
        if change == "admission_event":
            previous = env.events.list_for_session(env.session)[-1]
            payload = dict(env.bootstrap.events[2].payload)
            payload["coverage_admission"] = env.admission.model_copy(
                update={
                    "max_model_calls": 99,
                }
            ).model_dump(mode="json")
            env.events.append(
                SessionEvent.create(
                    session_id=env.session,
                    sequence=previous.sequence + 1,
                    event_type=EventType.TASK_PREPARED,
                    actor=EventActor.SYSTEM,
                    payload=payload,
                )
            )
        else:
            renewed = env.task_binding.model_copy(update={"binding_revision": 2})
            save_task_binding(
                env.dsn,
                deployment_namespace=env.kwargs["deployment_namespace"],
                binding=renewed,
                expected_previous_revision=1,
            )
        return records

    monkeypatch.setattr(coverage_storage, "read_manifest", read_then_race)
    with pytest.raises(ValueError, match="changed before bind"):
        module.bootstrap_cloud_coverage(**env.kwargs)
    assert counts(env) == (0, 1, before[2] + 1 + (change == "admission_event"))
    events = env.events.list_for_session(env.session)
    assert sum(e.event_type == EventType.COVERAGE_ARTIFACT_MATERIALIZED for e in events) == 1
    assert not any(e.event_type == EventType.COVERAGE_MANIFEST_COMMITTED for e in events)


def test_component_passes_verified_bind_guards(component, monkeypatch):
    env = component
    monkeypatch.setattr(
        module.CoverageArtifacts, "publish", lambda self, identifier, *a: f"artifact://{identifier}"
    )
    monkeypatch.setattr(
        module.CoverageArtifacts,
        "manifest",
        lambda self, identifier, *a: (f"artifact://{identifier}", env.wire.records),
    )
    module.bootstrap_cloud_coverage(**env.kwargs)
    assert env.store.bind.call_args.kwargs == {
        "fence": env.fence,
        "expected_stream_revision": env.events[-1].sequence,
        "task_binding_digest": env.task_binding.binding_digest,
    }
