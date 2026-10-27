"""The published producer artifacts must match the executable domain contract."""

import json
from pathlib import Path

from agent_core.domain.native_script import NativeScriptManifest
from agent_core.domain.native_script_protocol import (
    ScriptInvocation,
    ScriptObservation,
    ScriptResponse,
)


def test_native_script_schemas_are_generated_from_current_producer_models() -> None:
    root = Path(__file__).resolve().parents[1] / "docs/contracts/native-script-v1"
    for name, model in (
        ("manifest", NativeScriptManifest),
        ("invocation", ScriptInvocation),
        ("response", ScriptResponse),
        ("observation", ScriptObservation),
    ):
        assert json.loads((root / f"{name}.schema.json").read_text()) == model.model_json_schema()
    contract = json.loads((root / "contract.json").read_text())
    assert contract["workerAdmission"] is False
    assert contract["coverageAuthority"] is False
    assert contract["bundleScriptAbi"] == "unsupported"
