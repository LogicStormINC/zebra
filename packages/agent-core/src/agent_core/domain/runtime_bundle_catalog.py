"""Native component allowlist; provenance does not attest deployed configuration."""

from typing import Any

from agent_core.domain.runtime_bundle_json import json_digest
from agent_core.domain.runtime_bundle_types import (
    ArtifactPin,
    BundleValue,
    EmptyParameters,
    InstructionsParameters,
    ModelParameters,
)

# Tuples keep the authoritative allowlist immutable; callers receive fresh JSON values.
_SOURCE_REFS = (
    ("engine", "packages/agent-core/src/agent_core/harness/loop.py"),
    ("execution", "packages/agent-runtime/src/agent_runtime/harness.py"),
    ("model", "packages/agent-core/src/agent_core/domain/modeling.py"),
    ("instructions", "packages/agent-context/src/agent_context/prompt_layout.py"),
    ("context", "packages/agent-core/src/agent_core/ports/context_compiler.py"),
    ("memory", "packages/agent-core/src/agent_core/ports/agent_memory_gateway.py"),
    ("content", "packages/agent-security/src/agent_security/content_guard.py"),
    ("native", "packages/agent-core/src/agent_core/domain/agent_capabilities.py"),
    ("addons", "packages/agent-core/src/agent_core/application/plugin_resolution.py"),
    ("tools", "packages/agent-tools/src/agent_tools/registry.py"),
    ("lifecycle", "packages/agent-runtime/src/agent_runtime/runtime_instance_lifecycle.py"),
    ("policy", "packages/agent-security/src/agent_security/policy.py"),
    ("sandbox", "packages/agent-runtime/src/agent_runtime/adapters/os_sandbox.py"),
    ("storage", "packages/agent-storage/src/agent_storage/runtime_composition.py"),
    ("transport", "packages/agent-integrations/src/agent_integrations/ag_ui/task_stream.py"),
    ("frontend", "packages/agent-core/src/agent_core/domain/client_sessions.py"),
    ("triggers", "packages/agent-core/src/agent_core/domain/task_schedule_authority.py"),
    ("budget", "packages/agent-core/src/agent_core/domain/coverage_model_budget.py"),
    ("verification", "packages/agent-core/src/agent_core/domain/verification_evidence.py"),
    ("operations", "apps/worker/src/zebra_agent_worker/runtime_instances.py"),
)


def _descriptor(domain: str, source: str) -> dict[str, Any]:
    parameter_types: dict[str, type[BundleValue]] = {
        "model": ModelParameters,
        "instructions": InstructionsParameters,
    }
    parameters = parameter_types.get(domain, EmptyParameters)
    configurable = domain in ("model", "instructions")
    descriptor = {
        "domain": domain,
        "id": f"cloud-agent/native/{domain}",
        "version": "1.0.0",
        "mode": "configurable" if configurable else "pinned",
        "reason": "validation-only" if configurable else "requires-runtime-assembly",
        "parameters_schema": parameters.model_json_schema(),
        "source_refs": [source],
    }
    return {**descriptor, "digest": json_digest(descriptor)}


def runtime_bundle_catalog() -> dict[str, Any]:
    return {
        "schema_version": "cloud-agent.component-catalog/1",
        "components": [_descriptor(domain, source) for domain, source in sorted(_SOURCE_REFS)],
    }


def runtime_bundle_catalog_digest() -> str:
    return json_digest(runtime_bundle_catalog())


def builtin_component_pin(domain: str) -> ArtifactPin:
    for name, source in _SOURCE_REFS:
        if domain == name:
            descriptor = _descriptor(name, source)
            return ArtifactPin(
                kind="component", id=descriptor["id"], version="1.0.0", digest=descriptor["digest"]
            )
    raise ValueError("unsupported native component")
