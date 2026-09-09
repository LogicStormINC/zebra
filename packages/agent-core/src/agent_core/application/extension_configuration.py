"""Revision-guarded configuration updates; configuration never activates execution."""

from typing import Literal

from pydantic import BaseModel, ConfigDict, StrictBool

from agent_core.domain.extensions import (
    ExtensionRevision,
    ExtensionScope,
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
