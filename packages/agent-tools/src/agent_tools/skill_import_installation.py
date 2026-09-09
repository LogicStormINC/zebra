"""Idempotent import installation, reusing scoped version and enable operations."""

from collections.abc import Callable

from agent_core.application.extension_configuration import (
    set_extension_enabled,
    update_skill_version,
)
from agent_core.application.skill_installations import create_skill_installation
from agent_core.domain.extensions import ExtensionScope, SkillInstallation
from agent_core.ports.extensions import (
    ExtensionPageRequest,
    ExtensionRevisionConflictError,
    ExtensionStore,
)


async def install_imported_skill(
    *, store: ExtensionStore, scope: ExtensionScope, imported: dict[str, object],
    before_save: Callable[[], None],
) -> SkillInstallation:
    payload = {key: imported[key] for key in ("skill_id", "version_id")}
    cursor: str | None = None
    matches: list[SkillInstallation] = []
    for _ in range(4):
        page = await store.list_skills(
            scope=scope, page=ExtensionPageRequest(limit=100, cursor=cursor),
        )
        for item in page.items:
            if item.scope != scope:
                raise ValueError("Skill scope mismatch")
            if item.version.skill_id == payload["skill_id"]:
                matches.append(item)
        cursor = page.next_cursor
        if cursor is None:
            break
    else:
        raise ValueError("Skill installation scan limit reached")
    if len(matches) > 1:
        raise ValueError("Multiple installations of this Skill")
    if matches:
        record = matches[0]
        if record.version.version_id != payload["version_id"]:
            record = await update_skill_version(
                store=store, scope=scope, object_id=record.installation_id,
                expected_revision=record.revision, payload=payload, before_save=before_save,
            )
    else:
        record, _ = await create_skill_installation(
            store=store, scope=scope, idempotency_key="github:" + str(payload["skill_id"]),
            payload=payload, before_save=before_save,
        )
    if (record.version.skill_id, record.version.version_id) != (
        payload["skill_id"], payload["version_id"],
    ):
        raise ExtensionRevisionConflictError("Installation version changed during import")
    if record.enabled:
        return record
    enabled = await set_extension_enabled(
        store=store, scope=scope, kind="skill", object_id=record.installation_id,
        expected_revision=record.revision, enabled=True, before_save=before_save,
    )
    if not isinstance(enabled, SkillInstallation):
        raise ValueError("Invalid Skill installation result")
    return enabled
