"""New discriminators keep old Definition/snapshot canonical bytes unchanged."""

from typing import Literal

from agent_core.domain.bundle_definition import BundleDefinitionSnapshot, BundleDefinitionVersion
from agent_core.domain.script_bundle import ScriptRuntimeAssembly


class ScriptDefinitionVersion(BundleDefinitionVersion):
    schema_version: Literal["agent-definition/3"] = "agent-definition/3"  # type: ignore[assignment]
    runtime_assembly: ScriptRuntimeAssembly


class ScriptDefinitionSnapshot(BundleDefinitionSnapshot):
    snapshot_schema_version: Literal["agent-definition-snapshot/3"] = "agent-definition-snapshot/3"  # type: ignore[assignment]
    bound_version: ScriptDefinitionVersion
