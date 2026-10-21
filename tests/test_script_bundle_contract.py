"""New producer schemas stay explicit; prior A/P2 producer artifacts remain separate."""

import json
from pathlib import Path

import pytest
from agent_core.domain.native_script_receipt import NativeScriptEvent
from agent_core.domain.script_bundle import NativeScriptPlan, ScriptBundle, ScriptRuntimeAssembly
from agent_core.domain.script_definition import ScriptDefinitionSnapshot, ScriptDefinitionVersion

ROOT = Path("docs/contracts/native-script-worker-v1")


@pytest.mark.parametrize(
    "filename,model",
    [
        ("script-bundle.schema.json", ScriptBundle),
        ("script-plan.schema.json", NativeScriptPlan),
        ("script-assembly.schema.json", ScriptRuntimeAssembly),
        ("definition-v3.schema.json", ScriptDefinitionVersion),
        ("snapshot-v3.schema.json", ScriptDefinitionSnapshot),
        ("invocation-event.schema.json", NativeScriptEvent),
    ],
)
def test_exact_schema_export(filename, model):
    assert json.loads((ROOT / filename).read_bytes()) == model.model_json_schema()


def test_explicit_script_extension_seals_source_and_reader_identity():
    bundle = ScriptBundle.model_validate_json((ROOT / "example-script-bundle.json").read_bytes())
    assert bundle.base_bundle.manifest.engine.script_abi == "unsupported"
    assert bundle.scripts.abi == "cloud-agent.native-script/1"
    assert bundle.scripts.runner.runtime_class == "gvisor"
    assert '"source":' not in bundle.model_dump_json()
    from agent_core.domain.runtime_bundle import parse_runtime_bundle

    with pytest.raises(ValueError):
        parse_runtime_bundle(bundle.model_dump_json().encode())
