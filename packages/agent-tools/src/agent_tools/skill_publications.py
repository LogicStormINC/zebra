"""Internal durable ZIP publication; no installation or execution authority."""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from dataclasses import dataclass

from agent_core.domain.artifact_objects import (
    ArtifactObjectExpectation,
    ArtifactObjectPutRequest,
    ArtifactObjectReceipt,
)
from agent_core.domain.extensions import ExtensionScope, SkillVersion
from agent_core.domain.skill_publications import (
    SkillPublication,
    SkillPublicationFile,
    publication_identity,
)
from agent_core.ports.artifact_object_store import ArtifactObjectStorePort
from agent_core.ports.skill_publications import (
    UPLOAD_IDEMPOTENCY_KEY,
    SkillPublicationNotFoundError,
    SkillPublicationStorePort,
)

from agent_tools.skill_packages import validate_skill_package


def _candidate(archive: bytes, scope: ExtensionScope, deployment: str) -> SkillPublication:
    package = validate_skill_package(archive)
    label = package.version or package.content_digest
    skill_id, version_id, artifact_id = publication_identity(deployment, scope, package.name, label)
    return SkillPublication(
        scope=scope, name=package.name, description=package.description, version_label=label,
        version=SkillVersion(skill_id=skill_id, version_id=version_id,
                             artifact_ref=f"artifact://{artifact_id}",
                             content_digest=package.content_digest),
        manifest=tuple(SkillPublicationFile(path=file.path, size=file.size, sha256=file.sha256)
                       for file in package.files),
        expectation=ArtifactObjectExpectation(deployment_namespace=deployment,
                                             artifact_id=artifact_id,
                                             sha256=package.archive_sha256,
                                             size_bytes=len(archive)),
    )


def _checked(record: SkillPublication, candidate: SkillPublication) -> SkillPublication:
    if not isinstance(record, SkillPublication):
        raise ValueError("publication store returned an invalid record")
    record = SkillPublication.model_validate(record.model_dump())
    if not record.same_candidate(candidate):
        raise ValueError("publication store returned a different immutable candidate")
    return record


def _put(
    objects: ArtifactObjectStorePort, candidate: SkillPublication, archive: bytes,
) -> ArtifactObjectReceipt:
    return objects.put_if_absent(
        ArtifactObjectPutRequest(expectation=candidate.expectation, payload=archive),
    )


async def publish_skill_package(
    *, archive: bytes, scope: ExtensionScope, deployment_namespace: str,
    store: SkillPublicationStorePort, objects: ArtifactObjectStorePort,
    idempotency_key: str | None = None,
    before_save: Callable[[], None] | None = None,
) -> SkillPublication:
    if idempotency_key is not None:
        idempotency_key = UPLOAD_IDEMPOTENCY_KEY.validate_python(idempotency_key)
    scope = ExtensionScope.model_validate(scope.model_dump())
    candidate = await asyncio.to_thread(_candidate, archive, scope, deployment_namespace)
    if before_save is not None:
        before_save()
    current = _checked(await store.reserve(
        scope=scope, publication=candidate,
        **({"idempotency_key": idempotency_key} if idempotency_key is not None else {}),
    ), candidate)
    if current.state == "ready":
        return current
    if before_save is not None:
        before_save()
    receipt = await asyncio.to_thread(_put, objects, candidate, archive)
    if not isinstance(receipt, ArtifactObjectReceipt):
        raise ValueError("object store returned an invalid receipt")
    receipt = ArtifactObjectReceipt.model_validate(receipt.model_dump())
    if receipt.expectation != candidate.expectation:
        raise ValueError("object store returned a foreign receipt")
    if before_save is not None:
        before_save()
    ready = _checked(await store.mark_ready(
        scope=scope, skill_id=candidate.version.skill_id,
        version_id=candidate.version.version_id, receipt=receipt,
    ), candidate)
    if ready.state != "ready":
        raise ValueError("publication store did not confirm ready state")
    if ready.receipt is None or ready.receipt.object_version != receipt.object_version:
        raise ValueError("publication store returned a different object version")
    return ready


@dataclass(frozen=True)
class SkillPublicationService:
    store: SkillPublicationStorePort
    objects: ArtifactObjectStorePort
    deployment_namespace: str

    async def publish(
        self, *, archive: bytes, scope: ExtensionScope, idempotency_key: str,
        before_save: Callable[[], None] | None = None,
    ) -> SkillPublication:
        return await publish_skill_package(
            archive=archive, scope=scope, idempotency_key=idempotency_key,
            store=self.store, objects=self.objects, deployment_namespace=self.deployment_namespace,
            before_save=before_save,
        )

    async def get(
        self, *, scope: ExtensionScope, skill_id: str, version_id: str,
    ) -> SkillPublication:
        scope = ExtensionScope.model_validate(scope.model_dump())
        record = await self.store.get(scope=scope, skill_id=skill_id, version_id=version_id)
        if not isinstance(record, SkillPublication):
            raise ValueError("publication store returned an invalid record")
        record = SkillPublication.model_validate(record.model_dump())
        if (record.scope != scope
                or record.expectation.deployment_namespace != self.deployment_namespace
                or record.version.skill_id != skill_id or record.version.version_id != version_id):
            raise SkillPublicationNotFoundError("publication not found in supplied scope")
        return record
