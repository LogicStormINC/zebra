"""Deterministic, exact-Version qualification of effect-free native bindings."""

from collections.abc import Callable
from time import monotonic
from typing import Annotated, Literal
from uuid import UUID, uuid4

from agent_core.domain.native_script import MAX_SCRIPT_INPUT_BYTES, NativeScript, ScriptValue
from agent_core.domain.native_script_protocol import ScriptInvocation, ScriptRunResult
from agent_core.domain.runtime_bundle_json import (
    canonical_json_bytes,
    json_digest,
    load_bundle_json,
)
from agent_core.domain.runtime_bundle_types import BundleScope, Digest, Identifier
from agent_core.domain.script_bundle import ScriptRuntimeAssembly
from pydantic import BeforeValidator, Field

_UUID = Annotated[UUID, BeforeValidator(lambda v: UUID(v) if isinstance(v, str) else v)]


class ScriptEvalCase(ScriptValue):
    name: Identifier
    binding: Identifier
    arguments: dict[str, str | int | bool]
    expected: dict[str, str | int | bool]


class ScriptEvalSuite(ScriptValue):
    schema_version: Literal["cloud-agent.native-script-evaluation/1"]
    scope: BundleScope
    definition_id: _UUID
    version_id: _UUID
    definition_digest: Annotated[str, Field(pattern=r"^[0-9a-f]{64}$")]
    assembly_digest: Digest
    evaluator_actor: Identifier
    policy_version: Identifier
    cases: Annotated[
        tuple[ScriptEvalCase, ...],
        Field(min_length=1, max_length=32),
        BeforeValidator(lambda v: tuple(v) if type(v) is list else v),
    ]

    @property
    def digest(self) -> str:
        return json_digest(self.model_dump(mode="json"))

    def check(self, assembly: ScriptRuntimeAssembly) -> None:
        bindings = {b.name: b for b in assembly.native_scripts.bindings}
        if (
            self.scope != assembly.bundle.manifest.scope
            or self.assembly_digest != assembly.assembly_digest
            or {c.binding for c in self.cases} != set(bindings)
            or len({c.name for c in self.cases}) != len(self.cases)
        ):
            raise ValueError("EVAL_SUITE_BINDING_MISMATCH")
        if sum(bindings[c.binding].manifest.timeout_seconds for c in self.cases) > 60:
            raise ValueError("EVAL_SUITE_BUDGET_EXCEEDED")
        for case in self.cases:
            manifest = bindings[case.binding].manifest
            manifest.input.validate_record(case.arguments)
            manifest.output.validate_record(case.expected)
            example = ScriptInvocation(
                abi=manifest.abi,
                invocation_id="00000000-0000-0000-0000-000000000001",
                manifest_digest=manifest.digest,
                arguments=case.arguments,
            )
            if (
                len(canonical_json_bytes(example.model_dump(mode="json"))) > MAX_SCRIPT_INPUT_BYTES
                or len(canonical_json_bytes(case.expected)) > manifest.max_output_bytes
            ):
                raise ValueError("EVAL_CASE_BYTES_EXCEEDED")
            # A verifier qualification cannot approve an explicitly rejecting expected result.
            if manifest.kind == "verifier" and case.expected.get("passed") is not True:
                raise ValueError("EVAL_VERIFIER_EXPECTATION_INVALID")


def evaluate_scripts(
    suite: ScriptEvalSuite,
    assembly: ScriptRuntimeAssembly,
    *,
    authorize: Callable[[], None],
    execute: Callable[[NativeScript, bytes], ScriptRunResult],
    source: Callable[[str], NativeScript],
) -> dict[str, object]:
    """The trusted parent computes the decision; no submitted passed/gate field."""
    suite.check(assembly)
    deadline = monotonic() + 60
    bindings = {b.name: b for b in assembly.native_scripts.bindings}
    cases: list[dict[str, object]] = []
    for case in suite.cases:
        if monotonic() >= deadline:
            raise TimeoutError("EVAL_DEADLINE")
        authorize()
        binding = bindings[case.binding]
        script = source(binding.manifest.digest)
        if script.manifest != binding.manifest:
            raise ValueError("EVAL_SOURCE_BINDING_MISMATCH")
        invocation = ScriptInvocation(
            abi=script.manifest.abi,
            invocation_id=str(uuid4()),
            manifest_digest=script.manifest.digest,
            arguments=case.arguments,
        )
        raw = canonical_json_bytes(invocation.model_dump(mode="json"))
        result = execute(script, raw)
        authorize()
        from hashlib import sha256

        observation = result.observation
        if (
            observation.invocation_id != invocation.invocation_id
            or observation.manifest_digest != script.manifest.digest
            or observation.input_digest != "sha256:" + sha256(raw).hexdigest()
            or monotonic() >= deadline
        ):
            raise ValueError("EVAL_OBSERVATION_BINDING_MISMATCH")
        passed = (
            observation.status == "succeeded"
            and result.output_json is not None
            and load_bundle_json(result.output_json) == case.expected
        )
        cases.append(
            {
                "name": case.name,
                "binding": case.binding,
                "passed": passed,
                "expectedDigest": json_digest(case.expected),
                "observation": observation.model_dump(mode="json"),
            }
        )
    return {
        "schema_version": "cloud-agent.native-script-evaluation-result/1",
        "suiteDigest": suite.digest,
        "policy_version": suite.policy_version,
        "evaluator_actor": suite.evaluator_actor,
        "definitionDigest": suite.definition_digest,
        "assemblyDigest": suite.assembly_digest,
        "passed": all(c["passed"] for c in cases),
        "cases": cases,
    }
