"""Exact package-created Skill origins, including the pre-origin one-click format."""

from hashlib import sha256

from agent_core.domain.extensions import ExtensionScope, SkillInstallation
from agent_core.domain.plugin_installations import PluginInstallation, PluginSkillBinding
from agent_core.ports.extensions import ExtensionPageRequest
from agent_core.ports.plugin_installations import PluginInstallationStore


def plugin_skill_key(package_digest: str, component_id: str) -> str:
    return "plugin-skill-" + sha256((package_digest + ":" + component_id).encode()).hexdigest()


def plugin_skill_identifier(package_digest: str, component_id: str) -> str:
    return "skill_" + sha256(
        b"zebra:skill-installation:create:v1\0"
        + plugin_skill_key(package_digest, component_id).encode("ascii")
    ).hexdigest()


def managed_plugin_skill(record: PluginInstallation, binding: PluginSkillBinding) -> bool:
    return binding.installation.plugin_origin is not None or (
        binding.installation.installation_id
        == plugin_skill_identifier(record.package.package_digest, binding.component_id)
    )


async def managed_skill_ids(
    store: PluginInstallationStore | None, scope: ExtensionScope,
    skills: tuple[SkillInstallation, ...],
) -> frozenset[str]:
    """No display-name guessing; a package key deterministically created these IDs.

    ponytail: the compatibility scan is bounded to 1,000 scoped Plugins; add an
    indexed origin lookup before raising this per-user installation ceiling.
    """
    managed = {item.installation_id for item in skills if item.plugin_origin is not None}
    unresolved = {item.installation_id for item in skills} - managed
    if not unresolved or store is None:
        return frozenset(managed)
    cursor = None
    for _ in range(10):
        page = await store.list(scope=scope, page=ExtensionPageRequest(limit=100, cursor=cursor))
        for record in page.items:
            if record.scope != scope:
                raise ValueError("foreign Plugin installation")
            # Retain provenance after rebinding an old one-click installation.
            records: tuple[PluginInstallation, ...] = (record,)
            if record.revision > 1:
                original = await store.get_creation(
                    scope=scope, installation_id=record.installation_id
                )
                if original.scope != scope or original.installation_id != record.installation_id:
                    raise ValueError("foreign Plugin creation")
                records += (original,)
            for source in records:
                managed.update(
                    binding.installation.installation_id
                    for binding in source.bindings
                    if isinstance(binding, PluginSkillBinding)
                    and binding.installation.installation_id in unresolved
                    and managed_plugin_skill(source, binding)
                )
        if page.next_cursor is None:
            return frozenset(managed)
        if page.next_cursor == cursor:
            raise ValueError("Plugin pagination did not advance")
        cursor = page.next_cursor
    raise ValueError("Plugin ownership catalog exceeds limit")
