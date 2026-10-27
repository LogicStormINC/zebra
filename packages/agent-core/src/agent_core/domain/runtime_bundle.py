"""Offline native Runtime Bundle validation; no asset resolution or execution."""

from typing import Annotated, Any, Literal, Self

from pydantic import BeforeValidator, Field, model_validator

from agent_core.domain.runtime_bundle_catalog import (
    builtin_component_pin,
    runtime_bundle_catalog,
    runtime_bundle_catalog_digest,
)
from agent_core.domain.runtime_bundle_json import (
    MAX_BUNDLE_BYTES,
    canonical_json_bytes,
    json_digest,
    load_bundle_json,
)
from agent_core.domain.runtime_bundle_types import (
    ArtifactPin,
    BundleScope,
    BundleValue,
    Digest,
    EngineBinding,
    InstructionsDomain,
    InstructionsParameters,
    ModelDomain,
    ModelParameters,
    PinnedDomain,
    RuntimeDomains,
)

__all__ = [
    "MAX_BUNDLE_BYTES",
    "ArtifactPin",
    "BundleScope",
    "EngineBinding",
    "InstructionsDomain",
    "InstructionsParameters",
    "ModelDomain",
    "ModelParameters",
    "PinnedDomain",
    "ResolvedRuntimeBundle",
    "RuntimeBundleEnvelope",
    "RuntimeDomains",
    "builtin_component_pin",
    "canonical_runtime_bundle_bytes",
    "parse_runtime_bundle",
    "require_bundle_compatibility",
    "runtime_bundle_catalog",
    "runtime_bundle_catalog_digest",
    "runtime_bundle_json_schema",
    "seal_runtime_bundle",
]


def _json_tuple(value: object) -> object:
    return tuple(value) if type(value) is list else value


Pins = Annotated[tuple[ArtifactPin, ...], BeforeValidator(_json_tuple)]


def _pin_key(pin: ArtifactPin) -> tuple[str, str, str]:
    return pin.kind, pin.id, pin.version


class ResolvedRuntimeBundle(BundleValue):
    schema_version: Literal["cloud-agent.runtime-bundle/1"]
    scope: BundleScope
    engine: EngineBinding
    baseline_config: ArtifactPin
    catalog_digest: Digest
    domains: RuntimeDomains
    lock: Annotated[Pins, Field(min_length=25, max_length=128)]
    build_evidence: Annotated[Pins, Field(min_length=1, max_length=32)]

    @model_validator(mode="after")
    def closure(self) -> Self:
        if self.baseline_config.kind != "baseline-config":
            raise ValueError("baseline configuration pin required")
        if self.catalog_digest != runtime_bundle_catalog_digest():
            raise ValueError("unsupported native catalog")
        references = [
            self.engine.image,
            self.baseline_config,
            self.domains.model.parameters.provider_profile,
            self.domains.instructions.parameters.output_schema,
            *self.build_evidence,
        ]
        for domain in RuntimeDomains.model_fields:
            component = getattr(self.domains, domain).component
            if component != builtin_component_pin(domain):
                raise ValueError("unsupported native component")
            references.append(component)
        if any(pin.kind != "build-evidence" for pin in self.build_evidence):
            raise ValueError("build evidence pin required")
        if len(set(self.build_evidence)) != len(self.build_evidence):
            raise ValueError("duplicate build evidence")
        identities = [(pin.kind, pin.id) for pin in self.lock]
        if len(set(identities)) != len(identities):
            raise ValueError("duplicate lock identity")
        if list(self.lock) != sorted(self.lock, key=_pin_key) or set(self.lock) != set(references):
            raise ValueError("lock must be exact sorted reference closure")
        return self


class RuntimeBundleEnvelope(BundleValue):
    schema_version: Literal["cloud-agent.bundle-envelope/1"]
    bundle_digest: Digest
    manifest: ResolvedRuntimeBundle

    @model_validator(mode="after")
    def digest_matches(self) -> Self:
        if self.bundle_digest != json_digest(self.manifest.model_dump(mode="json")):
            raise ValueError("bundle digest mismatch")
        return self


def canonical_runtime_bundle_bytes(manifest: ResolvedRuntimeBundle) -> bytes:
    checked = ResolvedRuntimeBundle.model_validate(manifest)
    return canonical_json_bytes(checked.model_dump(mode="json"))


def seal_runtime_bundle(manifest: ResolvedRuntimeBundle) -> RuntimeBundleEnvelope:
    checked = ResolvedRuntimeBundle.model_validate(manifest)
    envelope = RuntimeBundleEnvelope(
        schema_version="cloud-agent.bundle-envelope/1",
        bundle_digest=json_digest(checked.model_dump(mode="json")),
        manifest=checked,
    )
    canonical_json_bytes(envelope.model_dump(mode="json"))
    return envelope


def parse_runtime_bundle(raw: bytes) -> RuntimeBundleEnvelope:
    try:
        envelope = RuntimeBundleEnvelope.model_validate(load_bundle_json(raw))
        canonical_json_bytes(envelope.model_dump(mode="json"))
        return envelope
    except (ValueError, TypeError, OverflowError, RecursionError):
        raise ValueError("INVALID_BUNDLE") from None


def runtime_bundle_json_schema() -> dict[str, Any]:
    return RuntimeBundleEnvelope.model_json_schema()


def require_bundle_compatibility(
    envelope: RuntimeBundleEnvelope,
    *,
    supported_bundle_abis: frozenset[str],
    supported_component_digests: frozenset[str],
) -> None:
    checked = RuntimeBundleEnvelope.model_validate(envelope)
    if checked.manifest.engine.bundle_abi not in supported_bundle_abis or any(
        getattr(checked.manifest.domains, name).component.digest not in supported_component_digests
        for name in RuntimeDomains.model_fields
    ):
        raise ValueError("INCOMPATIBLE_BUNDLE")
