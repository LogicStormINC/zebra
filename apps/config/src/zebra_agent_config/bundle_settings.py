"""Private operator approvals for the first executable Bundle subset."""

import hashlib
import hmac
import json
import re
from dataclasses import asdict
from typing import Annotated, Literal, Self

from agent_core.domain.runtime_assembly import RuntimeAssembly, RuntimeProviderProfile
from agent_core.domain.runtime_bundle import RuntimeBundleEnvelope
from agent_core.domain.runtime_bundle_json import load_bundle_json
from agent_core.domain.runtime_bundle_types import ArtifactPin, BundleScope, BundleValue
from pydantic import Field, model_validator

from zebra_agent_config.private_configuration import read_private_configuration
from zebra_agent_config.settings import ZebraAgentSettings


def baseline_digest(
    settings: ZebraAgentSettings, key: str, *, include_disabled_agui_defaults: bool = False
) -> str:
    """Pin all non-model settings; HMAC keeps credential-bearing settings private."""
    if not re.fullmatch(r"[0-9a-f]{64}", key):
        raise ValueError("INVALID_BASELINE_KEY")
    values = asdict(settings)
    del values["model"]
    del values["runtime_bundle_config"]
    del values["runtime_gate_termination_config"]
    del values["runtime_instance_id"]  # Process-only identity cannot drift existing Task baselines.
    del values["runtime_gate_config"]  # Transport opt-in preserves historical baselines.
    del values["bundle_management_config"]
    del values["publication_management_config"]
    del values["script_validation_config"]
    del values["plugin_admission_config"]
    if not settings.host_execution_authority.enabled:
        del values["host_execution_authority"]
    # ponytail: retain published defaults; the exact intermediate encoding is read-only history.
    if not include_disabled_agui_defaults and not (
        settings.stream.agui_profiles_enabled or settings.stream.agui_native_interaction_enabled
    ):
        del values["stream"]["agui_profiles_enabled"]
        del values["stream"]["agui_native_interaction_enabled"]
    encoded = json.dumps(
        values, sort_keys=True, ensure_ascii=True, allow_nan=False, separators=(",", ":")
    ).encode()
    return "sha256:" + hmac.new(bytes.fromhex(key), encoded, hashlib.sha256).hexdigest()


class RuntimeExecutionCatalog(BundleValue):
    schema_version: Literal["cloud-agent.execution-catalog/1"]
    scope: BundleScope
    image: ArtifactPin
    baseline_config: ArtifactPin
    baseline_key: Annotated[str, Field(pattern=r"^[0-9a-f]{64}$", repr=False, exclude=True)]
    providers: Annotated[tuple[RuntimeProviderProfile, ...], Field(min_length=1, max_length=32)]
    output_schema: ArtifactPin
    build_evidence: Annotated[tuple[ArtifactPin, ...], Field(min_length=1, max_length=32)]

    @model_validator(mode="after")
    def validate_approvals(self) -> Self:
        if (
            self.image.kind != "image"
            or self.baseline_config.kind != "baseline-config"
            or self.output_schema.kind != "output-schema"
            or any(pin.kind != "build-evidence" for pin in self.build_evidence)
            or len({profile.pin for profile in self.providers}) != len(self.providers)
            or len(set(self.build_evidence)) != len(self.build_evidence)
        ):
            raise ValueError("INVALID_EXECUTION_CATALOG")
        return self

    def resolve(self, bundle: RuntimeBundleEnvelope) -> RuntimeAssembly:
        manifest = bundle.manifest
        if (
            manifest.scope != self.scope
            or manifest.engine.image != self.image
            or manifest.baseline_config != self.baseline_config
            or manifest.domains.instructions.parameters.output_schema != self.output_schema
            or any(pin not in self.build_evidence for pin in manifest.build_evidence)
        ):
            raise ValueError("BUNDLE_ASSETS_NOT_APPROVED")
        pin = manifest.domains.model.parameters.provider_profile
        profile = next((item for item in self.providers if item.pin == pin), None)
        if profile is None:
            raise ValueError("BUNDLE_PROVIDER_NOT_APPROVED")
        return RuntimeAssembly(bundle=bundle, provider_profile=profile)


def load_execution_catalog(path: str | None) -> RuntimeExecutionCatalog:
    """No error contains private file contents or filesystem paths."""
    if not path:
        raise ValueError("BUNDLE_ASSEMBLY_NOT_CONFIGURED")
    try:
        raw = read_private_configuration(path, max_bytes=262_144)
        payload = load_bundle_json(raw)
        if (
            isinstance(payload, dict)
            and payload.get("schema_version") == "cloud-agent.execution-catalog/2"
        ):
            from zebra_agent_config.native_script import ScriptExecutionCatalog

            return ScriptExecutionCatalog.model_validate_json(
                json.dumps(payload, ensure_ascii=True)
            )
        return RuntimeExecutionCatalog.model_validate_json(json.dumps(payload, ensure_ascii=True))
    except (OSError, ValueError, TypeError, RecursionError):
        raise ValueError("INVALID_EXECUTION_CATALOG") from None
