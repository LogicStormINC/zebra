"""Install only server-published versions; no package or runtime I/O."""

from collections.abc import Callable
from hashlib import sha256

from pydantic import BaseModel, ConfigDict, TypeAdapter, ValidationError

from agent_core.application.plugin_component_ownership import plugin_skill_key
from agent_core.domain.extensions import (
    ExtensionIdempotencyKey,
    ExtensionScope,
    OpaqueExtensionId,
    PluginSkillOrigin,
    SkillInstallation,
)
from agent_core.domain.skill_publications import SkillPublication
from agent_core.ports.extensions import (
    ExtensionNotFoundError,
    ExtensionRevisionConflictError,
    ExtensionStore,
)
from agent_core.ports.skill_publications import SkillPublicationNotFoundError

_KEY: TypeAdapter[str] = TypeAdapter(ExtensionIdempotencyKey)


class SkillInstallationCreate(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    skill_id: OpaqueExtensionId
    version_id: OpaqueExtensionId


def _checked(
    record: SkillInstallation, scope: ExtensionScope, identifier: str,
) -> SkillInstallation:
    if not isinstance(record, SkillInstallation):
        raise RuntimeError("Invalid persisted installation type")
    record = SkillInstallation.model_validate(record.model_dump())
    if record.scope != scope or record.installation_id != identifier:
        raise ExtensionNotFoundError("Extension configuration was not found")
    return record


async def _replay(
    store: ExtensionStore, scope: ExtensionScope, identifier: str,
    request: SkillInstallationCreate, original: SkillInstallation,
    plugin_origin: PluginSkillOrigin | None,
) -> tuple[SkillInstallation, bool]:
    original = _checked(original, scope, identifier)
    if original.revision != 1 or original.enabled:
        raise RuntimeError("Invalid persisted installation creation")
    if original.plugin_origin != plugin_origin:
        # Legacy deterministic package installations predate explicit origin metadata.
        if original.plugin_origin is not None or plugin_origin is None:
            raise ExtensionRevisionConflictError("Idempotency key origin differs")
    if (original.version.skill_id, original.version.version_id) != (
        request.skill_id, request.version_id,
    ):
        raise ExtensionRevisionConflictError("Idempotency key request differs")
    current = _checked(await store.get_skill(
        scope=scope, installation_id=identifier,
    ), scope, identifier)
    return current, False


async def create_skill_installation(
    *, store: ExtensionStore, scope: ExtensionScope, idempotency_key: str,
    payload: object,
    before_save: Callable[[], None] | None = None,
    plugin_origin: PluginSkillOrigin | None = None,
) -> tuple[SkillInstallation, bool]:
    key = _KEY.validate_python(idempotency_key)
    if plugin_origin is not None and key != plugin_skill_key(
        plugin_origin.package_digest, plugin_origin.component_id
    ):
        raise ValueError("package Skill origin disagrees with creation key")
    request = SkillInstallationCreate.model_validate(payload)
    scope = ExtensionScope.model_validate(scope.model_dump())
    identifier = "skill_" + sha256(
        b"zebra:skill-installation:create:v1\0" + key.encode("ascii"),
    ).hexdigest()
    try:
        try:
            original = await store.get_skill_creation(scope=scope, installation_id=identifier)
        except ExtensionNotFoundError:
            pass
        else:
            return await _replay(store, scope, identifier, request, original, plugin_origin)
        try:
            publication = await store.get_skill_publication(
                scope=scope, skill_id=request.skill_id, version_id=request.version_id,
            )
        except SkillPublicationNotFoundError:
            raise ExtensionNotFoundError("Skill publication was not found") from None
        if not isinstance(publication, SkillPublication):
            raise RuntimeError("Invalid persisted publication type")
        publication = SkillPublication.model_validate(publication.model_dump())
        if (publication.scope != scope or publication.state != "ready"
                or publication.version.skill_id != request.skill_id
                or publication.version.version_id != request.version_id):
            raise ExtensionNotFoundError("Skill publication was not found")
        installation = SkillInstallation(
            scope=scope, installation_id=identifier, revision=1, enabled=False,
            version=publication.version, plugin_origin=plugin_origin,
        )
        # ponytail: ready publications are immutable; a future revoke lifecycle must
        # atomically check publication eligibility and create the installation.
        try:
            if before_save is not None:
                before_save()
            await store.save_skill(scope=scope, installation=installation, expected_revision=None)
        except ExtensionRevisionConflictError:
            original = await store.get_skill_creation(scope=scope, installation_id=identifier)
            return await _replay(store, scope, identifier, request, original, plugin_origin)
    except ValidationError:
        raise RuntimeError("Invalid persisted extension configuration") from None
    return installation, True
