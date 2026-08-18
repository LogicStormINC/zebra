"""EXT-PLUGIN-01: plugin manifest, lifecycle, and registry tests."""

from __future__ import annotations

from pathlib import Path

import pytest
from agent_core.domain.plugins import (
    PluginInstallRecord,
    PluginLifecycleState,
    PluginManifest,
    PluginTransitionError,
    transition_plugin_state,
)
from agent_integrations.plugins import (
    PluginRegistry,
    PluginRegistryError,
    load_manifest,
)


def _manifest(**overrides: object) -> dict[str, object]:
    document: dict[str, object] = {
        "manifest_version": "0.1",
        "id": "code-helper",
        "version": "1.2.0",
        "scope": "user",
        "entry": {"kind": "skill-bundle", "skill_root": "skills/code"},
    }
    document.update(overrides)
    return document


def test_manifest_identity_and_digest_are_stable() -> None:
    manifest = PluginManifest.validate_document(_manifest())
    same = PluginManifest.validate_document(_manifest(publisher="acme"))
    other = PluginManifest.validate_document(_manifest(version="1.3.0"))
    assert manifest.content_digest() == PluginManifest.validate_document(
        _manifest()
    ).content_digest()
    assert manifest.content_digest() != other.content_digest()
    assert same.component_identity.startswith("acme/code-helper@1.2.0#")
    assert manifest.effective_namespace == "user"


def test_manifest_rejects_invalid_shapes() -> None:
    with pytest.raises(ValueError):
        PluginManifest.validate_document(_manifest(id="UPPER"))
    with pytest.raises(ValueError):
        PluginManifest.validate_document(_manifest(version="1.2"))
    with pytest.raises(ValueError):
        PluginManifest.validate_document(_manifest(scope="global"))
    with pytest.raises(ValueError):
        PluginManifest.validate_document(
            _manifest(entry={"kind": "mcp-http", "url": "http://insecure"})
        )
    with pytest.raises(ValueError):
        PluginManifest.validate_document(
            {
                **_manifest(),
                "provenance": {"digest": "md5:abc"},
            }
        )


def test_lifecycle_requires_layered_transitions() -> None:
    state = PluginLifecycleState.AVAILABLE
    state = transition_plugin_state(state, PluginLifecycleState.INSTALLED)
    state = transition_plugin_state(state, PluginLifecycleState.ENABLED)
    assert state is PluginLifecycleState.ENABLED
    with pytest.raises(PluginTransitionError):
        transition_plugin_state(
            PluginLifecycleState.AVAILABLE, PluginLifecycleState.APPROVED
        )


def test_install_record_pins_content_digest() -> None:
    manifest = PluginManifest.validate_document(_manifest())
    record = PluginInstallRecord(
        manifest=manifest,
        installed_digest=manifest.content_digest(),
        installed_at="2026-08-16T00:00:00Z",
        operator="admin",
    )
    assert record.installed_digest.startswith("sha256:")
    with pytest.raises(ValueError):
        PluginInstallRecord(
            manifest=manifest,
            installed_digest="sha256:" + "0" * 64,
            installed_at="2026-08-16T00:00:00Z",
            operator="admin",
        )


def test_registry_lifecycle_and_enablement() -> None:
    registry = PluginRegistry()
    manifest = PluginManifest.validate_document(_manifest())
    registry.register_available(manifest)
    install = registry.install(
        "code-helper", operator="admin", installed_at="2026-08-16T00:00:00Z"
    )
    assert install.installed_digest == manifest.content_digest()
    registry.enable("code-helper")
    assert [m.id for m in registry.enabled_entries()] == ["code-helper"]
    registry.disable("code-helper")
    assert registry.enabled_entries() == ()
    registry.uninstall("code-helper")
    with pytest.raises(PluginRegistryError):
        registry.get("code-helper")


def test_registry_rejects_double_registration_and_wrong_state() -> None:
    registry = PluginRegistry()
    manifest = PluginManifest.validate_document(_manifest())
    registry.register_available(manifest)
    with pytest.raises(PluginRegistryError):
        registry.register_available(manifest)
    with pytest.raises(PluginRegistryError):
        registry.enable("code-helper")


def test_load_manifest_validates_bundle_layout(tmp_path: Path) -> None:
    bundle = tmp_path / "code-helper"
    (bundle / "skills" / "code").mkdir(parents=True)
    (bundle / "skills" / "code" / "SKILL.md").write_text("# code\n")
    import json

    (bundle / "plugin.json").write_text(json.dumps(_manifest()), encoding="utf-8")
    manifest = load_manifest(bundle)
    assert manifest.id == "code-helper"

    (bundle / "skills" / "code" / "SKILL.md").unlink()
    with pytest.raises(PluginRegistryError):
        load_manifest(bundle)

    missing = tmp_path / "empty-bundle"
    missing.mkdir()
    with pytest.raises(PluginRegistryError):
        load_manifest(missing)
