"""Explicit script closure over an unchanged Runtime Bundle v1 capsule."""

from typing import Annotated, Literal, Self

from pydantic import BeforeValidator, Field, model_validator

from agent_core.domain.native_script import NativeScriptManifest
from agent_core.domain.runtime_assembly import RuntimeAssembly
from agent_core.domain.runtime_bundle import RuntimeBundleEnvelope
from agent_core.domain.runtime_bundle_json import json_digest
from agent_core.domain.runtime_bundle_types import ArtifactPin, BundleValue, Digest

Array = BeforeValidator(lambda value: tuple(value) if type(value) is list else value)
ScopeName = Annotated[str, Field(min_length=1, max_length=128, pattern=r"^[A-Za-z0-9_.:-]+$")]


class ScriptRunnerProfile(BundleValue):
    mode: Literal["development", "production"]
    runtime_class: Literal["os-sandbox", "gvisor"]
    python: Annotated[str, Field(min_length=2, max_length=1024, pattern=r"^/[^\x00]+$")]

    @model_validator(mode="after")
    def production_isolation(self) -> Self:
        if self.mode == "production" and self.runtime_class != "gvisor":
            raise ValueError("production native scripts require gVisor")
        return self


class ScriptBinding(BundleValue):
    name: Annotated[str, Field(pattern=r"^native\.[a-z][a-z0-9_]{1,63}$")]
    manifest: NativeScriptManifest
    scopes: Annotated[tuple[ScopeName, ...], Array, Field(min_length=1, max_length=32)]

    @model_validator(mode="after")
    def invocation_contract(self) -> Self:
        if len(set(self.scopes)) != len(self.scopes):
            raise ValueError("duplicate native script scope")
        fields = {field.name: field.type for field in self.manifest.input.fields}
        expected = {
            "context": {"user_input": "string"},
            "verifier": {"tool_status": "string", "tool_output": "string"},
        }
        if self.manifest.kind in expected and fields != expected[self.manifest.kind]:
            raise ValueError("unsupported Worker script input contract")
        return self

    @property
    def references(self) -> tuple[ArtifactPin, ArtifactPin]:
        return (
            ArtifactPin(
                kind="component",
                version=self.manifest.version,
                id=f"native-script/{self.manifest.name}",
                digest=self.manifest.digest,
            ),
            ArtifactPin(
                kind="component",
                version=self.manifest.version,
                id=f"native-source/{self.manifest.name}",
                digest=self.manifest.source_digest,
            ),
        )


class NativeScriptPlan(BundleValue):
    schema_version: Literal["cloud-agent.native-script-plan/1"]
    abi: Literal["cloud-agent.native-script/1"]
    runner: ScriptRunnerProfile
    bindings: Annotated[tuple[ScriptBinding, ...], Array, Field(min_length=1, max_length=8)]
    lock: Annotated[tuple[ArtifactPin, ...], Array, Field(min_length=2, max_length=16)]

    @model_validator(mode="after")
    def exact_closure(self) -> Self:
        names = [binding.name for binding in self.bindings]
        if names != sorted(set(names)):
            raise ValueError("script bindings must have unique sorted names")
        for kind in ("context", "verifier"):
            if sum(binding.manifest.kind == kind for binding in self.bindings) > 1:
                raise ValueError("only one context/verifier binding per script plan")
        references = [pin for binding in self.bindings for pin in binding.references]
        if len(set((pin.kind, pin.id) for pin in references)) != len(references):
            raise ValueError("duplicate script asset identity")
        expected = sorted(references, key=lambda pin: (pin.kind, pin.id, pin.version))
        if list(self.lock) != expected:
            raise ValueError("script lock must equal complete sorted reference closure")
        return self


class ScriptBundle(BundleValue):
    schema_version: Literal["cloud-agent.script-bundle/1"]
    base_bundle: RuntimeBundleEnvelope
    scripts: NativeScriptPlan
    bundle_digest: Digest

    @model_validator(mode="after")
    def digest_matches(self) -> Self:
        if self.bundle_digest != json_digest(
            self.model_dump(mode="json", exclude={"bundle_digest"})
        ):
            raise ValueError("script bundle digest mismatch")
        return self


class ScriptRuntimeAssembly(RuntimeAssembly):
    schema_version: Literal["cloud-agent.script-assembly/1"]
    native_scripts: NativeScriptPlan

    @property
    def script_bundle(self) -> ScriptBundle:
        payload = {
            "schema_version": "cloud-agent.script-bundle/1",
            "base_bundle": self.bundle.model_dump(mode="json"),
            "scripts": self.native_scripts.model_dump(mode="json"),
        }
        return ScriptBundle.model_validate(payload | {"bundle_digest": json_digest(payload)})

    @property
    def required_reference(self) -> str:
        return "script-bundle/" + self.script_bundle.bundle_digest.removeprefix("sha256:") + "@1"


def parse_runtime_assembly(value: object) -> RuntimeAssembly:
    payload = value.model_dump() if isinstance(value, RuntimeAssembly) else value
    if (
        isinstance(payload, dict)
        and payload.get("schema_version") == "cloud-agent.script-assembly/1"
    ):
        return ScriptRuntimeAssembly.model_validate(payload)
    return RuntimeAssembly.model_validate(payload)
