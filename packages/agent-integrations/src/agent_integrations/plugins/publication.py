"""Publish only operator-approved directories; recovery reads pinned immutable objects."""

from __future__ import annotations

import asyncio
import json
from dataclasses import dataclass
from hashlib import sha256
from pathlib import Path
from uuid import NAMESPACE_URL, uuid5

from agent_core.domain.artifact_objects import (
    ArtifactObjectExpectation,
    ArtifactObjectPutRequest,
    ArtifactObjectReceipt,
)
from agent_core.domain.identifiers import ArtifactId
from agent_core.domain.plugin_installations import PluginDigest, PluginPackagePin
from agent_core.domain.skill_publications import SkillPublicationFile
from agent_core.ports.artifact_object_store import ArtifactObjectStorePort
from pydantic import TypeAdapter

from agent_integrations.plugins.artifact_codec import decode_plugin_package, encode_plugin_package
from agent_integrations.plugins.package_integrity import ValidatedPluginPackage, load_plugin_package


@dataclass(frozen=True)
class PluginPackagePublicationService:
    bundle_root: Path
    allowed_digests: tuple[str, ...]
    objects: ArtifactObjectStorePort
    deployment_namespace: str

    async def publish(self, *, package_digest: str) -> PluginPackagePin:
        digest = TypeAdapter(PluginDigest).validate_python(package_digest)
        if digest not in self.allowed_digests:
            raise ValueError("package digest is not approved")
        package = await asyncio.to_thread(
            load_plugin_package,
            self.bundle_root / digest.removeprefix("sha256:"),
        )
        if package.package_digest != digest:
            raise ValueError("approved package digest disagrees with actual package")
        payload = encode_plugin_package(package)
        expectation = ArtifactObjectExpectation(
            deployment_namespace=self.deployment_namespace,
            artifact_id=ArtifactId(
                uuid5(
                    NAMESPACE_URL,
                    json.dumps(
                        ("zebra.plugin.package.v1", self.deployment_namespace, digest),
                        separators=(",", ":"),
                    ),
                )
            ),
            sha256=sha256(payload).hexdigest(),
            size_bytes=len(payload),
        )
        receipt = await asyncio.to_thread(
            self.objects.put_if_absent,
            ArtifactObjectPutRequest(expectation=expectation, payload=payload),
        )
        receipt = ArtifactObjectReceipt.model_validate(receipt.model_dump())
        pin = PluginPackagePin(
            manifest=package.manifest,
            canonical_manifest=package.canonical_manifest,
            manifest_digest=package.manifest_digest,
            package_digest=digest,
            files=tuple(
                SkillPublicationFile(path=file.path, size=file.size, sha256=file.sha256)
                for file in package.files
            ),
            expectation=expectation,
            receipt=receipt,
        )
        await self.read(pin)
        return pin

    async def read(self, pin: PluginPackagePin) -> ValidatedPluginPackage:
        pin = PluginPackagePin.model_validate(pin.model_dump())
        if pin.expectation.deployment_namespace != self.deployment_namespace:
            raise ValueError("package belongs to another deployment")
        payload = await asyncio.to_thread(
            self.objects.read_version_verified,
            pin.expectation,
            pin.receipt.object_version,
        )
        if (
            len(payload) != pin.expectation.size_bytes
            or sha256(payload).hexdigest() != pin.expectation.sha256
        ):
            raise ValueError("immutable package object disagrees with expectation")
        package = decode_plugin_package(payload)
        if (
            package.package_digest != pin.package_digest
            or package.manifest_digest != pin.manifest_digest
            or package.manifest != pin.manifest
            or package.canonical_manifest != pin.canonical_manifest
            or tuple((file.path, file.size, file.sha256) for file in package.files)
            != tuple((file.path, file.size, file.sha256) for file in pin.files)
        ):
            raise ValueError("immutable package disagrees with pinned facts")
        return package
