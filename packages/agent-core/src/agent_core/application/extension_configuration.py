"""Revision-guarded configuration updates; configuration never activates execution."""

from collections.abc import Callable
from typing import Literal

from pydantic import BaseModel, ConfigDict, StrictBool

from agent_core.application.mcp_connections import McpConnectionCreate
from agent_core.application.skill_installations import SkillInstallationCreate
from agent_core.domain.extensions import (
    ExtensionRevision,
    ExtensionScope,
    McpAuthMode,
    McpAuthState,
    McpConnection,
    OpaqueExtensionId,
    SkillInstallation,
)
from agent_core.ports.extensions import (
    ExtensionNotFoundError,
    ExtensionRevisionConflictError,
    ExtensionStore,
)


class _EnabledUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    scope: ExtensionScope
    kind: Literal["skill", "mcp"]
    object_id: OpaqueExtensionId
    expected_revision: ExtensionRevision
    enabled: StrictBool


async def set_extension_enabled(
    *, store: ExtensionStore, scope: ExtensionScope, kind: Literal["skill", "mcp"],
    object_id: str, expected_revision: int, enabled: bool,
    before_save: Callable[[], None] | None = None,
) -> SkillInstallation | McpConnection:
    update = _EnabledUpdate(
        scope=scope, kind=kind, object_id=object_id,
        expected_revision=expected_revision, enabled=enabled,
    )
    record = (
        await store.get_skill(scope=update.scope, installation_id=update.object_id)
        if update.kind == "skill"
        else await store.get_mcp(scope=update.scope, connection_id=update.object_id)
    )
    identity_matches = (
        isinstance(record, SkillInstallation) and record.installation_id == update.object_id
        if update.kind == "skill"
        else isinstance(record, McpConnection) and record.connection_id == update.object_id
    )
    if not identity_matches or record.scope != update.scope:
        raise ExtensionNotFoundError("Extension configuration was not found")
    if record.revision != update.expected_revision:
        raise ExtensionRevisionConflictError("Extension revision has changed")
    if record.enabled == update.enabled:
        return record
    values = record.model_dump() | {"enabled": update.enabled, "revision": record.revision + 1}
    if before_save is not None:
        before_save()
    if isinstance(record, SkillInstallation):
        installation = SkillInstallation.model_validate(values)
        await store.save_skill(
            scope=update.scope, installation=installation,
            expected_revision=update.expected_revision,
        )
        return installation
    connection = McpConnection.model_validate(values)
    await store.save_mcp(
        scope=update.scope, connection=connection, expected_revision=update.expected_revision,
    )
    return connection


async def update_mcp_configuration(
    *, store: ExtensionStore, scope: ExtensionScope, object_id: str,
    expected_revision: int, payload: object,
    before_save: Callable[[], None] | None = None,
) -> McpConnection:
    request = McpConnectionCreate.model_validate(payload)
    update = _EnabledUpdate(scope=scope, kind="mcp", object_id=object_id,
                            expected_revision=expected_revision, enabled=False)
    current = await store.get_mcp(scope=scope, connection_id=update.object_id)
    if current.scope != scope or current.connection_id != object_id:
        raise ExtensionNotFoundError("Extension configuration was not found")
    if current.revision != update.expected_revision:
        raise ExtensionRevisionConflictError("Extension revision has changed")
    if (current.endpoint, current.transport, current.auth_mode) == (
        request.endpoint, request.transport, request.auth_mode,
    ):
        return current
    # Endpoint/auth changes invalidate any old endpoint-bound credential and catalog.
    connection = McpConnection(
        scope=scope, connection_id=object_id, revision=current.revision + 1,
        endpoint=request.endpoint, transport=request.transport, auth_mode=request.auth_mode,
        enabled=False, credential_ref=None,
        auth_state=(McpAuthState.NOT_REQUIRED if request.auth_mode is McpAuthMode.NONE
                    else McpAuthState.PENDING),
    )
    if before_save is not None:
        before_save()
    await store.save_mcp(scope=scope, connection=connection, expected_revision=expected_revision)
    return connection


async def update_skill_version(
    *, store: ExtensionStore, scope: ExtensionScope, object_id: str,
    expected_revision: int, payload: object,
    before_save: Callable[[], None] | None = None,
) -> SkillInstallation:
    request = SkillInstallationCreate.model_validate(payload)
    update = _EnabledUpdate(scope=scope, kind="skill", object_id=object_id,
                            expected_revision=expected_revision, enabled=False)
    current = await store.get_skill(scope=scope, installation_id=update.object_id)
    if current.scope != scope or current.installation_id != object_id:
        raise ExtensionNotFoundError("Extension configuration was not found")
    if current.revision != expected_revision:
        raise ExtensionRevisionConflictError("Extension revision has changed")
    if current.version.skill_id != request.skill_id:
        raise ValueError("Upgrade must retain the same Skill identity")
    publication = await store.get_skill_publication(
        scope=scope, skill_id=request.skill_id, version_id=request.version_id,
    )
    if (publication.scope != scope or publication.state != "ready"
            or publication.version.skill_id != request.skill_id
            or publication.version.version_id != request.version_id):
        raise ExtensionNotFoundError("Skill publication was not found")
    if current.version == publication.version:
        return current
    # ponytail: ready publications are immutable, matching installation creation;
    # a future publication revoke lifecycle needs an atomic eligibility check.
    installation = SkillInstallation(
        scope=scope, installation_id=object_id, revision=current.revision + 1,
        enabled=current.enabled, version=publication.version,
    )
    if before_save is not None:
        before_save()
    await store.save_skill(
        scope=scope, installation=installation, expected_revision=expected_revision,
    )
    return installation
