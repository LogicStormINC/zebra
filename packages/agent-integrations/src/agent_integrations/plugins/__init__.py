"""Plugin lifecycle registry and loader (EXT-PLUGIN-01).

Bounded load/activate/deactivate/unload over the ADR-014 five-layer machine.
The registry owns install/enablement operator state only; it never grants
Task authority and never becomes a second execution-facts source.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from agent_core.domain.plugins import (
    PluginInstallRecord,
    PluginLifecycleState,
    PluginManifest,
    PluginTransitionError,
    transition_plugin_state,
)


class PluginRegistryError(ValueError):
    """Raised for invalid registry operations."""


@dataclass
class PluginRecord:
    manifest: PluginManifest
    state: PluginLifecycleState
    install: PluginInstallRecord | None = None


@dataclass
class PluginRegistry:
    """Operator-owned lifecycle state for discovered plugin packages."""

    _records: dict[str, PluginRecord] = field(default_factory=dict)

    def register_available(self, manifest: PluginManifest) -> PluginRecord:
        if manifest.id in self._records:
            raise PluginRegistryError(f"plugin {manifest.id} is already registered")
        record = PluginRecord(
            manifest=manifest,
            state=PluginLifecycleState.AVAILABLE,
        )
        self._records[manifest.id] = record
        return record

    def install(
        self,
        plugin_id: str,
        *,
        operator: str,
        installed_at: str,
    ) -> PluginInstallRecord:
        record = self._require(plugin_id)
        self._transition(record, PluginLifecycleState.INSTALLED)
        install = PluginInstallRecord(
            manifest=record.manifest,
            installed_digest=record.manifest.content_digest(),
            installed_at=installed_at,
            operator=operator,
        )
        record.install = install
        return install

    def enable(self, plugin_id: str) -> None:
        self._transition(self._require(plugin_id), PluginLifecycleState.ENABLED)

    def disable(self, plugin_id: str) -> None:
        record = self._require(plugin_id)
        if record.state is not PluginLifecycleState.ENABLED:
            raise PluginRegistryError(
                f"plugin {plugin_id} is not enabled"
            )
        self._transition(record, PluginLifecycleState.INSTALLED)

    def uninstall(self, plugin_id: str) -> None:
        record = self._require(plugin_id)
        self._transition(record, PluginLifecycleState.AVAILABLE)
        record.install = None
        del self._records[plugin_id]

    def get(self, plugin_id: str) -> PluginRecord:
        return self._require(plugin_id)

    def enabled_entries(self) -> tuple[PluginManifest, ...]:
        return tuple(
            record.manifest
            for record in self._records.values()
            if record.state is PluginLifecycleState.ENABLED
        )

    def _require(self, plugin_id: str) -> PluginRecord:
        record = self._records.get(plugin_id)
        if record is None:
            raise PluginRegistryError(f"plugin {plugin_id} is not registered")
        return record

    def _transition(
        self,
        record: PluginRecord,
        target: PluginLifecycleState,
    ) -> None:
        try:
            record.state = transition_plugin_state(record.state, target)
        except PluginTransitionError as error:
            raise PluginRegistryError(str(error)) from error


def load_manifest(bundle_root: Path) -> PluginManifest:
    """Load and validate one plugin manifest from a package directory."""
    manifest_path = bundle_root / "plugin.json"
    if not manifest_path.is_file():
        raise PluginRegistryError(
            f"plugin bundle {bundle_root} has no plugin.json manifest"
        )
    import json

    document = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest = PluginManifest.validate_document(document)
    _validate_entry_paths(bundle_root, manifest)
    return manifest


def _validate_entry_paths(bundle_root: Path, manifest: PluginManifest) -> None:
    entry = manifest.entry
    if entry.kind.value == "skill-bundle" and entry.skill_root is not None:
        skill_root = (bundle_root / entry.skill_root).resolve()
        bundle_resolved = bundle_root.resolve()
        if not str(skill_root).startswith(str(bundle_resolved)):
            raise PluginRegistryError("skill_root escapes the plugin bundle")
        if not (skill_root / "SKILL.md").is_file():
            raise PluginRegistryError(
                "skill-bundle entry does not contain SKILL.md at skill_root"
            )
    if entry.kind.value == "mcp-stdio" and entry.command is not None:
        if not Path(entry.command).is_absolute():
            raise PluginRegistryError("mcp-stdio command must be absolute")
