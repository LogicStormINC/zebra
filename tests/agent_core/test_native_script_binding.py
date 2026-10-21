"""Version closure, authorization and recoverable effect-free invocation state."""

import json
import sys
from dataclasses import replace
from hashlib import sha256
from pathlib import Path

import pytest
from agent_core.application.native_script import (
    NativeScriptInvocationService,
    NativeScriptUnavailable,
)
from agent_core.domain.bundle_definition import (
    BundleDefinitionSnapshot,
    BundleDefinitionVersion,
    parse_definition_snapshot,
    parse_definition_version,
    snapshot_from_version,
)
from agent_core.domain.native_script import NativeScript, NativeScriptManifest
from agent_core.domain.native_script_protocol import (
    ScriptInvocation,
    ScriptObservation,
    ScriptRunResult,
)
from agent_core.domain.native_script_receipt import fold_native_script
from agent_core.domain.runtime_bundle_json import canonical_json_bytes, json_digest
from agent_core.domain.script_bundle import (
    NativeScriptPlan,
    ScriptBinding,
    ScriptBundle,
    ScriptRuntimeAssembly,
)
from agent_core.domain.script_definition import ScriptDefinitionVersion
from zebra_agent_config.bundle_settings import load_execution_catalog
from zebra_agent_config.native_script import ScriptExecutionCatalog

from tests.agent_core.test_bundle_definition import NOW, bundle_version
from tests.test_bundle_assembly import approved_assembly, settings


def script(kind="tool", source=None):
    vectors = json.loads(Path("docs/contracts/native-script-v1/positive-vectors.json").read_text())
    vector = next(v for v in vectors if v["name"] == kind)
    manifest = vector["manifest"]
    source = source or vector["source"]
    if kind == "context":
        manifest["input"] = {"fields": [{"name": "user_input", "type": "string"}]}
    if kind == "verifier":
        manifest["input"] = {
            "fields": [{"name": n, "type": "string"} for n in ("tool_status", "tool_output")]
        }
    manifest["source_digest"] = "sha256:" + sha256(source.encode()).hexdigest()
    return NativeScript(NativeScriptManifest.model_validate(manifest), source.encode())


def binding(kind="tool", source=None):
    return ScriptBinding(
        name="native." + kind, manifest=script(kind, source).manifest, scopes=("native.read",)
    )


def plan(*bindings, python=None):
    python = python or str(Path(sys.executable).resolve())
    bindings = bindings or (binding(),)
    return NativeScriptPlan.model_validate(
        {
            "schema_version": "cloud-agent.native-script-plan/1",
            "abi": "cloud-agent.native-script/1",
            "runner": {"mode": "development", "runtime_class": "os-sandbox", "python": python},
            "bindings": sorted(bindings, key=lambda b: b.name),
            "lock": sorted(
                (pin for b in bindings for pin in b.references),
                key=lambda pin: (pin.kind, pin.id, pin.version),
            ),
        }
    )


def assembly_and_config(tmp_path, configured=None, *, bindings=None, sources=None):
    configured = configured or settings()
    base, catalog = approved_assembly(configured)
    plan_value = plan(*(bindings or (binding(),)))
    assembly = ScriptRuntimeAssembly(
        **base.model_dump(),
        schema_version="cloud-agent.script-assembly/1",
        native_scripts=plan_value,
    )
    scripts = sources or [script()]
    catalog.update(
        schema_version="cloud-agent.execution-catalog/2",
        script_plans=[plan_value.model_dump(mode="json")],
        scripts=[
            s.manifest.model_dump(mode="json") | {"source": s.source.decode()} for s in scripts
        ],
    )
    path = tmp_path / "catalog.json"
    path.write_text(json.dumps(catalog))
    path.chmod(0o600)
    return assembly, replace(configured, runtime_bundle_config=str(path)), catalog


def version(assembly):
    values = bundle_version().model_dump(exclude={"definition_digest", "schema_version"})
    return ScriptDefinitionVersion(
        **(
            values
            | {
                "runtime_assembly": assembly,
                "authority_issuer": assembly.bundle.manifest.scope.authority_issuer,
                "namespace_id": assembly.bundle.manifest.scope.namespace_id,
            }
        )
    )


class Journal:
    def __init__(self):
        self.events = []
        self.fail = None

    def read(self, invocation_id):
        return tuple(e for e in self.events if e.invocation_id == invocation_id)

    def append(self, event):
        if self.fail == event.phase:
            raise TimeoutError("commit unknown")
        self.events.append(event)
        if self.fail == "after-" + event.phase:
            raise TimeoutError("commit unknown")


class Runner:
    def __init__(self, *, failed=False):
        self.calls = 0
        self.failed = failed

    def run(self, script, raw, *, cancellation_check=None):
        self.calls += 1
        if cancellation_check:
            cancellation_check()
        invocation = ScriptInvocation.model_validate_json(raw)
        output = None if self.failed else canonical_json_bytes({"value": "hello"})
        return ScriptRunResult(
            ScriptObservation(
                abi=script.manifest.abi,
                invocation_id=invocation.invocation_id,
                manifest_digest=script.manifest.digest,
                input_digest="sha256:" + sha256(raw).hexdigest(),
                runtime_spec_digest="a" * 64,
                status="failed" if self.failed else "succeeded",
                reason="process_failed" if self.failed else "ok",
                output_digest=None if output is None else "sha256:" + sha256(output).hexdigest(),
            ),
            output,
        )


def service(journal, runner, fence="a", authorize=None):
    return NativeScriptInvocationService(
        task_id="task-1",
        snapshot_digest="sha256:" + "f" * 64,
        owner_fence="sha256:" + fence * 64,
        journal=journal,
        authorize=authorize or (lambda _: script()),
        runner=lambda: runner,
    )


def test_script_snapshots_are_distinct_immutable_roundtrip_and_source_free(tmp_path):
    assembly, configured, _ = assembly_and_config(tmp_path)
    checked = load_execution_catalog(configured.runtime_bundle_config)
    assert isinstance(checked, ScriptExecutionCatalog)
    assert checked.resolve_scripts(assembly.script_bundle) == assembly
    frozen = version(assembly)
    snapshot = snapshot_from_version(version=frozen, resolved_at=NOW)
    assert snapshot.snapshot_schema_version == "agent-definition-snapshot/3"
    assert parse_definition_snapshot(json.loads(snapshot.model_dump_json())) == snapshot
    assert parse_definition_version(json.loads(frozen.model_dump_json())) == frozen
    assert script().source.decode() not in snapshot.model_dump_json()
    assert '"source":' not in snapshot.model_dump_json()
    with pytest.raises(ValueError):
        BundleDefinitionVersion.model_validate_json(frozen.model_dump_json())
    with pytest.raises(ValueError):
        BundleDefinitionSnapshot.model_validate_json(snapshot.model_dump_json())
    changed = json.loads(snapshot.model_dump_json())
    changed["bound_version"]["runtime_assembly"]["native_scripts"]["bindings"][0]["scopes"] = [
        "other"
    ]
    with pytest.raises(ValueError):
        parse_definition_snapshot(changed)


@pytest.mark.parametrize(
    "patch",
    [
        {"lock": []},
        {"bindings": [binding().model_dump(mode="json")] * 2},
        {"abi": "cloud-agent.native-script/99"},
        {"runner": {"mode": "production", "runtime_class": "os-sandbox", "python": "/bin/python"}},
    ],
)
def test_script_plan_rejects_incomplete_or_ambiguous_closure(patch):
    with pytest.raises(ValueError):
        NativeScriptPlan.model_validate(plan().model_dump(mode="json") | patch)


def test_wrapper_cannot_change_base_or_manifest_without_resealing(tmp_path):
    assembly, _, _ = assembly_and_config(tmp_path)
    payload = assembly.script_bundle.model_dump(mode="json")
    payload["scripts"]["bindings"][0]["scopes"] = ["other"]
    with pytest.raises(ValueError):
        ScriptBundle.model_validate(payload)
    assert assembly.assembly_digest == json_digest(assembly.model_dump(mode="json"))


@pytest.mark.parametrize("failed", [False, True])
def test_terminal_replay_reauthorizes_without_executing(failed):
    journal, runner = Journal(), Runner(failed=failed)
    first = service(journal, runner).invoke(binding(), {"query": "x"}, logical_id="call")
    assert len(journal.events) == 2
    replay = service(journal, runner, "b").invoke(binding(), {"query": "x"}, logical_id="call")
    assert replay == first and runner.calls == 1

    def denied(_):
        raise NativeScriptUnavailable("revoked")

    with pytest.raises(NativeScriptUnavailable, match="revoked"):
        service(journal, runner, "c", denied).invoke(binding(), {"query": "x"}, logical_id="call")
    assert runner.calls == 1


@pytest.mark.parametrize("phase", ["started", "after-started", "completed", "after-completed"])
def test_commit_unknown_recovers_facts_before_dispatch(phase):
    journal, runner = Journal(), Runner()
    journal.fail = phase
    with pytest.raises(TimeoutError):
        service(journal, runner).invoke(binding(), {"query": "x"}, logical_id="call")
    prior_calls = runner.calls
    journal.fail = None
    recovered = service(journal, runner, "b").invoke(binding(), {"query": "x"}, logical_id="call")
    assert recovered.output_json == b'{"value":"hello"}'
    assert runner.calls == prior_calls + (0 if phase == "after-completed" else 1)
    assert fold_native_script(tuple(journal.events)).phase == "completed"


def test_same_fence_unresolved_is_not_retried_and_new_fence_attempts_are_bounded():
    journal, runner = Journal(), Runner()
    for fence in "abc":
        journal.fail = "completed"
        with pytest.raises(TimeoutError):
            service(journal, runner, fence).invoke(binding(), {"query": "x"}, logical_id="call")
        with pytest.raises(NativeScriptUnavailable, match="UNRESOLVED"):
            service(journal, runner, fence).invoke(binding(), {"query": "x"}, logical_id="call")
    with pytest.raises(NativeScriptUnavailable, match="UNRESOLVED"):
        service(journal, runner, "d").invoke(binding(), {"query": "x"}, logical_id="call")
    assert runner.calls == 3


def test_authority_loss_during_dispatch_leaves_only_unresolved_intent():
    journal = Journal()

    class Interrupted(Runner):
        def run(self, script, raw, *, cancellation_check=None):
            nonlocal active
            active = False
            cancellation_check()

    active = True

    def authorize(_):
        if not active:
            raise NativeScriptUnavailable("revoked")
        return script()

    with pytest.raises(NativeScriptUnavailable, match="revoked"):
        service(journal, Interrupted(), authorize=authorize).invoke(
            binding(), {"query": "x"}, logical_id="call"
        )
    assert [e.phase for e in journal.events] == ["started"]


def test_receipt_tamper_and_late_fence_are_refused():
    journal, runner = Journal(), Runner()
    service(journal, runner).invoke(binding(), {"query": "x"}, logical_id="call")
    start, completed = journal.events
    for changed in [
        completed.model_copy(update={"owner_fence": "sha256:" + "b" * 64}),
        completed.model_copy(update={"task_id": "other"}),
    ]:
        with pytest.raises(ValueError):
            fold_native_script((start, changed))
    with pytest.raises(ValueError):
        type(completed).model_validate(
            completed.model_dump() | {"output_json": '{"value":"tampered"}'}
        )


def test_busy_and_input_budget_fail_before_dispatch():
    journal, runner = Journal(), Runner()
    current = service(journal, runner)
    current._slot.acquire()
    try:
        with pytest.raises(NativeScriptUnavailable, match="BUSY"):
            current.invoke(binding(), {"query": "x"}, logical_id="call")
    finally:
        current._slot.release()
    wide = script().manifest.model_dump(mode="json")
    wide["input"] = {"fields": [{"name": name, "type": "string"} for name in ("a", "b", "c")]}
    wide_binding = ScriptBinding(
        name="native.wide",
        manifest=NativeScriptManifest.model_validate(wide),
        scopes=("native.read",),
    )
    with pytest.raises(NativeScriptUnavailable, match="INPUT_LIMIT"):
        current.invoke(wide_binding, {n: "中" * 1300 for n in ("a", "b", "c")}, logical_id="call")
    assert not journal.events and runner.calls == 0


@pytest.mark.parametrize(
    "change", ["source", "plan", "abi", "legacy", "runtime", "cloud", "limits"]
)
def test_worker_script_approval_drift_never_selects_latest(tmp_path, change):
    from zebra_agent_worker.native_scripts import approved_scripts

    assembly, configured, catalog = assembly_and_config(tmp_path)
    frozen = assembly.model_dump_json()
    if change == "source":
        catalog["scripts"][0]["source"] += "# drift"
    elif change == "plan":
        catalog["script_plans"][0]["bindings"][0]["scopes"] = ["other.read"]
    elif change == "abi":
        catalog["script_plans"][0]["abi"] = "cloud-agent.native-script/99"
    elif change == "legacy":
        catalog.pop("scripts")
        catalog.pop("script_plans")
        catalog["schema_version"] = "cloud-agent.execution-catalog/1"
    elif change == "runtime":
        configured = replace(
            configured, runtime=replace(configured.runtime, runtime_class="gvisor")
        )
    elif change == "cloud":
        configured = replace(configured, profile="cloud")
    else:
        configured = replace(configured, runtime=replace(configured.runtime, max_output_bytes=128))
    Path(configured.runtime_bundle_config).write_text(json.dumps(catalog))
    with pytest.raises((ValueError, PermissionError, NativeScriptUnavailable)):
        approved_scripts(configured, assembly)
    assert assembly.model_dump_json() == frozen


def test_api_resolves_only_new_wrapper_with_explicit_catalog(tmp_path):
    from zebra_agent_api.bundle_assembly import resolve_bundle_assembly

    assembly, configured, _ = assembly_and_config(tmp_path)
    payload = assembly.script_bundle.model_dump(mode="json")
    assert resolve_bundle_assembly(payload, configured.runtime_bundle_config) == assembly
    with pytest.raises(ValueError, match="BUNDLE_ASSEMBLY_REFUSED"):
        resolve_bundle_assembly(payload, None)
    payload["scripts"]["bindings"][0]["scopes"] = ["unapproved"]
    payload["bundle_digest"] = json_digest(
        {k: v for k, v in payload.items() if k != "bundle_digest"}
    )
    with pytest.raises(ValueError, match="BUNDLE_ASSEMBLY_REFUSED"):
        resolve_bundle_assembly(payload, configured.runtime_bundle_config)


def test_production_script_worker_requires_the_actual_pinned_image(tmp_path):
    from zebra_agent_worker.native_scripts import approved_scripts

    image = json.loads(Path("docs/contracts/runtime-bundle-v1/example-envelope.json").read_bytes())[
        "manifest"
    ]["engine"]["image"]["digest"]
    configured = settings()
    configured = replace(
        configured,
        profile="cloud",
        runtime=replace(
            configured.runtime,
            runtime_class="gvisor",
            image="runtime@" + image,
        ),
    )
    assembly, configured, catalog = assembly_and_config(tmp_path, configured)
    plan_payload = assembly.native_scripts.model_dump(mode="json")
    plan_payload["runner"] = {
        "mode": "production",
        "runtime_class": "gvisor",
        "python": "/usr/local/bin/python3.12",
    }
    assembly = ScriptRuntimeAssembly.model_validate(
        assembly.model_dump(mode="json") | {"native_scripts": plan_payload}
    )
    catalog["script_plans"] = [plan_payload]
    Path(configured.runtime_bundle_config).write_text(json.dumps(catalog))
    assert (
        approved_scripts(configured, assembly).resolve_scripts(assembly.script_bundle) == assembly
    )
    drifted = replace(
        configured, runtime=replace(configured.runtime, image="other@sha256:" + "0" * 64)
    )
    with pytest.raises(NativeScriptUnavailable, match="IMAGE"):
        approved_scripts(drifted, assembly)
