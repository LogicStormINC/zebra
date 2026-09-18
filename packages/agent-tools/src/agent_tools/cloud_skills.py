"""Private cloud package preparation, without filesystem or execution authority."""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Callable, Coroutine, Mapping
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from hashlib import sha256
from types import MappingProxyType
from typing import Any

from agent_core.domain.artifact_objects import (
    ArtifactObjectIntegrityError,
    ArtifactObjectNotFoundError,
    ArtifactObjectUnavailableError,
)
from agent_core.domain.extension_snapshots import ExtensionSnapshot
from agent_core.domain.extensions import ExtensionScope, SkillInstallation
from agent_core.domain.skill_publications import SkillPublication
from agent_core.ports.artifact_object_store import ArtifactObjectStorePort
from agent_core.ports.extensions import (
    AuthorizedSkill,
    ExtensionNotFoundError,
    ExtensionSkillAuthorizationError,
    SkillAuthorizationPort,
)

from agent_tools.skill_packages import (
    MAX_EXPANDED_BYTES,
    SkillPackageError,
    validate_skill_package,
)
from agent_tools.skills_catalog import (
    MAX_NAME_CHARS,
    MAX_SKILL_FILE_BYTES,
    MAX_SKILLS,
    SkillCatalogError,
    SkillMetadata,
    SkillReadResult,
    _validated_support_path,
)
from agent_tools.skills_scope import _bounded_text

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class _CloudEntry:
    metadata: SkillMetadata
    publication: SkillPublication


@dataclass(frozen=True)
class CloudSkillCatalog:
    """Frozen selection with live exact-scope authorization on every call."""

    snapshot: ExtensionSnapshot
    scope: ExtensionScope
    deployment_namespace: str
    store: SkillAuthorizationPort
    objects: ArtifactObjectStorePort
    route = "cloud_skill_catalog"
    guidance_origin = "CLOUD"

    def list(self, *, limit: int = 100) -> tuple[tuple[SkillMetadata, ...], int, bool]:
        if not isinstance(limit, int) or isinstance(limit, bool) or not 1 <= limit <= MAX_SKILLS:
            raise SkillCatalogError("invalid_limit", f"limit must be from 1 to {MAX_SKILLS}")
        values = tuple(entry.metadata for entry in self._live_entries().values())
        return values[:limit], 0, len(values) > limit

    def read(self, name: str, *, file_path: str = "SKILL.md") -> SkillReadResult:
        name = _bounded_text(name, "name", MAX_NAME_CHARS)
        before = self._live_entries()
        entry = before.get(name)
        if entry is None:
            entry = next(
                (candidate for candidate in before.values() if candidate.metadata.skill_id == name),
                None,
            )
        if entry is None:
            raise SkillCatalogError("skill_not_found", "skill is not available")
        path = _validated_support_path(file_path).as_posix()
        if path != file_path:
            raise SkillCatalogError("invalid_file_path", "file_path must be canonical")
        result = _load_entry(entry, self.objects, path)
        after = self._live_entries()
        if after != before:
            raise SkillCatalogError(
                "installation_unavailable", "cloud skill authorization changed during read"
            )
        return result

    def _live_entries(self) -> Mapping[str, _CloudEntry]:
        return _run_async(self._validate_live_entries)

    async def _validate_live_entries(self) -> Mapping[str, _CloudEntry]:
        try:
            authorized = await self.store.authorize_frozen_skills(
                scope=self.scope, installations=self.snapshot.skills
            )
        except (ExtensionNotFoundError, ExtensionSkillAuthorizationError):
            raise SkillCatalogError(
                "installation_unavailable", "cloud skill installation is unavailable"
            ) from None
        except Exception as exc:
            logger.exception("cloud Skill authorization backend failed")
            raise SkillCatalogError(
                "backend_unavailable", "cloud skill backend is unavailable"
            ) from exc
        if len(authorized) != len(self.snapshot.skills):
            raise SkillCatalogError(
                "installation_unavailable", "cloud skill installation is unavailable"
            )
        entries: dict[str, _CloudEntry] = {}
        retained = 0
        for frozen, live in zip(self.snapshot.skills, authorized, strict=True):
            publication = _validated_authorization(
                live, frozen, self.scope, self.deployment_namespace
            )
            retained += sum(file.size for file in publication.manifest)
            if retained > MAX_EXPANDED_BYTES:
                raise SkillCatalogError(
                    "catalog_too_large",
                    "cloud skill catalog exceeds byte limit",
                )
            metadata = _metadata(publication)
            if metadata.name in entries:
                raise SkillCatalogError("ambiguous_skill", "cloud skill names are ambiguous")
            entries[metadata.name] = _CloudEntry(metadata, publication)
        return MappingProxyType(dict(sorted(entries.items())))


async def prepare_cloud_skill_catalog(
    *,
    snapshot: ExtensionSnapshot,
    scope: ExtensionScope,
    deployment_namespace: str,
    session_id: str,
    turn_id: str,
    store: SkillAuthorizationPort,
    objects: ArtifactObjectStorePort,
) -> CloudSkillCatalog:
    """Verify only the exact turn snapshot's installed and published packages.

    Snapshot pins are not execution authority. The returned synchronous catalog
    rechecks live exact-scope state before every call. Package bytes remain lazy:
    list reads metadata only and read validates one selected ZIP in memory.
    """
    try:
        if not isinstance(snapshot, ExtensionSnapshot) or not isinstance(scope, ExtensionScope):
            raise ValueError
        snapshot = ExtensionSnapshot.model_validate(snapshot.model_dump())
        scope = ExtensionScope.model_validate(scope.model_dump())
        if (snapshot.scope, snapshot.session_id, snapshot.turn_id) != (scope, session_id, turn_id):
            raise ValueError
        if (
            not isinstance(deployment_namespace, str)
            or not deployment_namespace
            or deployment_namespace != deployment_namespace.strip()
            or len(deployment_namespace) > 255
        ):
            raise ValueError
    except (TypeError, ValueError):
        raise SkillCatalogError("invalid_snapshot", "cloud skill snapshot is invalid") from None

    return CloudSkillCatalog(snapshot, scope, deployment_namespace, store, objects)


def _validated_authorization(
    authorized: AuthorizedSkill,
    frozen: SkillInstallation,
    scope: ExtensionScope,
    deployment_namespace: str,
) -> SkillPublication:
    try:
        frozen_installation = SkillInstallation.model_validate(frozen.model_dump())
        current = SkillInstallation.model_validate(authorized.installation.model_dump())
        if current != frozen_installation or not current.enabled:
            raise ValueError
    except (AttributeError, TypeError, ValueError):
        raise SkillCatalogError(
            "installation_unavailable", "cloud skill installation is unavailable"
        ) from None
    try:
        publication = SkillPublication.model_validate(authorized.publication.model_dump())
        if (
            publication.scope != scope
            or publication.version != frozen_installation.version
            or publication.state != "ready"
            or publication.receipt is None
            or publication.expectation.deployment_namespace != deployment_namespace
        ):
            raise ValueError
        return publication
    except (AttributeError, TypeError, ValueError):
        raise SkillCatalogError(
            "publication_unavailable",
            "cloud skill publication is unavailable",
        ) from None


def _metadata(publication: SkillPublication) -> SkillMetadata:
    return SkillMetadata(
        name=publication.name,
        description=publication.description,
        source=publication.version.version_id,
        skill_id=publication.version.skill_id,
        version=publication.version_label,
        digest=publication.version.content_digest,
        namespace=publication.scope.namespace_id,
    )


def _load_entry(
    entry: _CloudEntry,
    objects: ArtifactObjectStorePort,
    path: str,
) -> SkillReadResult:
    publication = entry.publication
    receipt = publication.receipt
    if receipt is None:
        raise SkillCatalogError("package_integrity", "cloud skill package verification failed")
    try:
        payload = objects.read_version_verified(publication.expectation, receipt.object_version)
    except (
        ArtifactObjectIntegrityError,
        ArtifactObjectNotFoundError,
        ArtifactObjectUnavailableError,
    ):
        raise SkillCatalogError(
            "package_integrity", "cloud skill package verification failed"
        ) from None
    except Exception as exc:
        logger.exception("cloud Skill object backend failed")
        raise SkillCatalogError(
            "backend_unavailable", "cloud skill backend is unavailable"
        ) from exc
    if not isinstance(payload, bytes):
        raise SkillCatalogError("package_integrity", "cloud skill package verification failed")
    try:
        if (
            len(payload) != publication.expectation.size_bytes
            or sha256(payload).hexdigest() != publication.expectation.sha256
        ):
            raise SkillPackageError("archive_integrity")
        package = validate_skill_package(payload)
        manifest = tuple((file.path, file.size, file.sha256) for file in package.files)
        if (
            manifest != tuple((file.path, file.size, file.sha256) for file in publication.manifest)
            or package.content_digest != publication.version.content_digest
            or package.name != publication.name
            or package.description != publication.description
            or (package.version or package.content_digest) != publication.version_label
        ):
            raise SkillPackageError("publication_integrity")
    except SkillPackageError:
        raise SkillCatalogError(
            "package_integrity",
            "cloud skill package verification failed",
        ) from None
    files = {file.path: file.content for file in package.files}
    selected = files.get(path)
    if selected is None:
        raise SkillCatalogError("file_not_found", "skill file does not exist")
    if len(selected) > MAX_SKILL_FILE_BYTES:
        raise SkillCatalogError("file_too_large", "skill file exceeds 32768 bytes")
    if b"\x00" in selected:
        raise SkillCatalogError("binary_file", "binary skill files are blocked")
    try:
        content = selected.decode("utf-8")
    except UnicodeDecodeError:
        raise SkillCatalogError("invalid_encoding", "skill files must be UTF-8") from None
    metadata = SkillMetadata(
        **{
            **entry.metadata.__dict__,
            "license": package.license,
            "compatibility": package.compatibility,
            "metadata": MappingProxyType(dict(package.metadata)),
        }
    )
    return SkillReadResult(metadata, path, content, len(selected))


_ASYNC_BRIDGE = ThreadPoolExecutor(max_workers=1, thread_name_prefix="cloud-skill-bridge")


def _run_async[T](factory: Callable[[], Coroutine[Any, Any, T]]) -> T:
    """Run one store check from the synchronous Tool boundary."""

    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return asyncio.run(factory())
    # Synchronous tool adapters embedded inside an async host cannot nest loops.
    return _ASYNC_BRIDGE.submit(asyncio.run, factory()).result()
