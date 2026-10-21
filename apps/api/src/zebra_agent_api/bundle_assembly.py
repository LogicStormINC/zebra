"""Resolve only locally approved Bundle assets before registry transactions."""

from agent_core.domain.runtime_assembly import RuntimeAssembly
from agent_core.domain.runtime_bundle import parse_runtime_bundle
from agent_core.domain.runtime_bundle_json import canonical_json_bytes
from zebra_agent_config.bundle_settings import load_execution_catalog


def resolve_bundle_assembly(payload: object, config_path: str | None) -> RuntimeAssembly:
    try:
        bundle = parse_runtime_bundle(canonical_json_bytes(payload))
        return load_execution_catalog(config_path).resolve(bundle)
    except (ValueError, TypeError, OverflowError, RecursionError):
        raise ValueError("BUNDLE_ASSEMBLY_REFUSED") from None
