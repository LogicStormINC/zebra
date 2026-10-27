"""Resolve only locally approved Bundle assets before registry transactions."""

from agent_core.domain.runtime_assembly import RuntimeAssembly
from agent_core.domain.runtime_bundle import parse_runtime_bundle
from agent_core.domain.runtime_bundle_json import canonical_json_bytes
from agent_core.domain.script_bundle import ScriptBundle
from zebra_agent_config.bundle_settings import load_execution_catalog
from zebra_agent_config.native_script import ScriptExecutionCatalog


def resolve_bundle_assembly(payload: object, config_path: str | None) -> RuntimeAssembly:
    try:
        if (
            isinstance(payload, dict)
            and payload.get("schema_version") == "cloud-agent.script-bundle/1"
        ):
            catalog = load_execution_catalog(config_path)
            if not isinstance(catalog, ScriptExecutionCatalog):
                raise ValueError("scripts are not configured")
            return catalog.resolve_scripts(ScriptBundle.model_validate(payload))
        bundle = parse_runtime_bundle(canonical_json_bytes(payload))
        return load_execution_catalog(config_path).resolve(bundle)
    except (PermissionError, ValueError, TypeError, OverflowError, RecursionError):
        raise ValueError("BUNDLE_ASSEMBLY_REFUSED") from None
