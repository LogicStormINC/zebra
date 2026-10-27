"""Qualification executes real sandbox scripts and rejects incomplete/forged evidence."""

import copy
import json
import sys
from uuid import uuid4

import pytest
from agent_runtime.native_script import NativeScriptRunner
from agent_runtime.native_script_eval import ScriptEvalSuite, evaluate_scripts

from tests.agent_core.test_native_script_binding import assembly_and_config, script
from tests.agent_runtime.test_native_script_runner import OsSandboxRuntime, spec


def suite_for(assembly, **updates):
    return ScriptEvalSuite.model_validate(
        {
            "schema_version": "cloud-agent.native-script-evaluation/1",
            "scope": assembly.bundle.manifest.scope.model_dump(mode="json"),
            "definition_id": str(uuid4()),
            "version_id": str(uuid4()),
            "definition_digest": "a" * 64,
            "assembly_digest": assembly.assembly_digest,
            "evaluator_actor": "native-evaluator",
            "policy_version": "eval-policy/1",
            "cases": [
                {
                    "name": "exact-output",
                    "binding": "native.tool",
                    "arguments": {"query": "input"},
                    "expected": {"value": "hello"},
                }
            ],
        }
        | updates
    )


@pytest.mark.skipif(sys.platform != "darwin", reason="real Seatbelt; gVisor proof separate")
@pytest.mark.parametrize("expected,passed", [("hello", True), ("incorrect", False)])
def test_real_runner_grades_outputs_not_submitted_boolean(tmp_path, expected, passed):
    assembly, _, _ = assembly_and_config(tmp_path)
    suite = suite_for(
        assembly,
        cases=[
            {
                "name": "case",
                "binding": "native.tool",
                "arguments": {"query": "x"},
                "expected": {"value": expected},
            }
        ],
    )
    current = spec()
    runner = NativeScriptRunner(
        OsSandboxRuntime(current), current, python=assembly.native_scripts.runner.python
    )
    checks = []
    result = evaluate_scripts(
        suite,
        assembly,
        authorize=lambda: checks.append(True),
        source=lambda _: script(),
        execute=runner.run,
    )
    assert result["passed"] is passed and len(checks) == 2
    assert result["cases"][0]["observation"]["status"] == "succeeded"
    assert result["suiteDigest"] == suite.digest
    assert "hello" not in json.dumps(result)  # results retain digests, never source/input/output.


@pytest.mark.parametrize(
    "patch",
    [
        {"passed": True},
        {"cases": []},
        {"cases": [{"name": "c", "binding": "foreign", "arguments": {}, "expected": {}}]},
        {"assembly_digest": "sha256:" + "0" * 64},
    ],
)
def test_suite_closed_and_complete_before_runner(tmp_path, patch):
    assembly, _, _ = assembly_and_config(tmp_path)
    with pytest.raises(ValueError):
        suite = suite_for(assembly, **patch)
        suite.check(assembly)


def test_duplicate_cases_and_input_shape_refused(tmp_path):
    assembly, _, _ = assembly_and_config(tmp_path)
    suite = suite_for(assembly)
    value = suite.model_dump(mode="json")
    value["cases"] *= 2
    with pytest.raises(ValueError):
        ScriptEvalSuite.model_validate(value).check(assembly)
    value = copy.deepcopy(suite.model_dump(mode="json"))
    value["cases"][0]["arguments"] = {"query": True}
    with pytest.raises(ValueError):
        ScriptEvalSuite.model_validate(value).check(assembly)


def test_authorization_failure_never_runs(tmp_path):
    assembly, _, _ = assembly_and_config(tmp_path)

    def denied():
        raise PermissionError("current grant revoked")

    def unexpected(*args):
        raise AssertionError("execution after revoke")

    with pytest.raises(PermissionError):
        evaluate_scripts(
            suite_for(assembly), assembly, authorize=denied, execute=unexpected, source=unexpected
        )


def test_exported_suite_schema_keeps_array_cardinality_contract():
    from pathlib import Path

    schema = ScriptEvalSuite.model_json_schema()
    cases = schema["properties"]["cases"]
    assert cases["minItems"] == 1 and cases["maxItems"] == 32
    assert "minLength" not in cases and "maxLength" not in cases
    exported = json.loads(
        Path("docs/contracts/native-script-evaluation/suite.schema.json").read_text()
    )
    assert exported == schema
