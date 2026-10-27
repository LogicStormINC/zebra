"""Explicit private script approval; no latest lookup or source in Task snapshots."""

from typing import Annotated, Literal, Self

from agent_core.domain.native_script import NativeScript, NativeScriptManifest
from agent_core.domain.runtime_bundle_types import Digest, Text
from agent_core.domain.script_bundle import NativeScriptPlan, ScriptBundle, ScriptRuntimeAssembly
from pydantic import Field, model_validator

from zebra_agent_config.bundle_settings import RuntimeExecutionCatalog


class ApprovedScript(NativeScriptManifest):
    # Source belongs only in this private operator approval, never in the Bundle.
    source: Annotated[Text, Field(min_length=1, max_length=16_384, repr=False)]

    @property
    def script(self) -> NativeScript:
        manifest = NativeScriptManifest.model_validate(self.model_dump(exclude={"source"}))
        return NativeScript(manifest, self.source.encode("utf-8"))

    @model_validator(mode="after")
    def source_matches(self) -> Self:
        _ = self.script
        return self


class ScriptExecutionCatalog(RuntimeExecutionCatalog):
    schema_version: Literal["cloud-agent.execution-catalog/2"]  # type: ignore[assignment]
    script_plans: Annotated[tuple[NativeScriptPlan, ...], Field(min_length=1, max_length=8)]
    scripts: Annotated[tuple[ApprovedScript, ...], Field(min_length=1, max_length=16, repr=False)]

    @model_validator(mode="after")
    def approved_closure(self) -> Self:
        scripts = {item.script.manifest.digest for item in self.scripts}
        if len(scripts) != len(self.scripts) or len(set(self.script_plans)) != len(
            self.script_plans
        ):
            raise ValueError("duplicate script approval")
        if any(
            binding.manifest.digest not in scripts
            for plan in self.script_plans
            for binding in plan.bindings
        ):
            raise ValueError("script plan has an unapproved source")
        return self

    def script_for(self, digest: Digest) -> NativeScript:
        for item in self.scripts:
            script = item.script
            if script.manifest.digest == digest:
                return script
        raise PermissionError("NATIVE_SCRIPT_NOT_APPROVED")

    def resolve_scripts(self, bundle: ScriptBundle) -> ScriptRuntimeAssembly:
        base = self.resolve(bundle.base_bundle)
        if bundle.scripts not in self.script_plans:
            raise PermissionError("NATIVE_SCRIPT_PLAN_NOT_APPROVED")
        for binding in bundle.scripts.bindings:
            self.script_for(binding.manifest.digest)
        return ScriptRuntimeAssembly(
            **base.model_dump(),
            schema_version="cloud-agent.script-assembly/1",
            native_scripts=bundle.scripts,
        )
