"""Cloud Plugin directory package integrity; no runtime activation or execution."""

from __future__ import annotations

import json
import os
from collections.abc import Iterator
from contextlib import contextmanager
from hashlib import sha256
from pathlib import Path
from types import SimpleNamespace

import pytest
from agent_core.domain.plugins import PluginManifest
from agent_integrations.plugins import load_manifest

SKILL = b"---\nname: research\ndescription: Research guide\n---\nOriginal guide\n"


def _legacy_bundle(tmp_path: Path) -> Path:
    bundle = tmp_path / "bundle"
    skill = bundle / "skills" / "research"
    skill.mkdir(parents=True)
    (skill / "SKILL.md").write_bytes(SKILL)
    (bundle / "plugin.json").write_text(
        json.dumps(
            {
                "manifest_version": "0.1",
                "id": "public-research",
                "version": "1.0.0",
                "scope": "user",
                "entry": {"kind": "skill-bundle", "skill_root": "skills/research"},
            }
        )
    )
    return bundle


def test_package_digest_pins_actual_skill_bytes(tmp_path: Path) -> None:
    from agent_integrations.plugins.package_integrity import load_plugin_package

    bundle = _legacy_bundle(tmp_path)
    legacy_digest = load_manifest(bundle).content_digest()
    first = load_plugin_package(bundle)
    (bundle / "skills" / "research" / "SKILL.md").write_bytes(SKILL + b"Tampered\n")
    second = load_plugin_package(bundle)
    assert first.manifest_digest == second.manifest_digest == legacy_digest
    assert first.package_digest != second.package_digest
    assert first.files[0].content == SKILL


def _v2(**overrides: object) -> dict[str, object]:
    document: dict[str, object] = {
        "manifest_version": "0.2",
        "id": "public-research",
        "version": "1.0.0",
        "publisher": "internal-team",
        "components": [
            {"id": "research-guide", "kind": "skill-bundle", "skill_root": "skills/research"},
            {"id": "reference-docs", "kind": "mcp-http", "connection_slot": "reference-docs"},
        ],
    }
    document.update(overrides)
    return document


def test_v2_components_and_digest_cover_canonical_manifest_and_sorted_files(tmp_path: Path) -> None:
    from agent_integrations.plugins.package_integrity import load_plugin_package

    bundle = _legacy_bundle(tmp_path)
    (bundle / "plugin.json").write_text(json.dumps(_v2()))
    assets = bundle / "skills" / "research" / "assets"
    assets.mkdir()
    (assets / "z.bin").write_bytes(b"\x00\xff")
    first = load_plugin_package(bundle)
    assert [component.kind for component in first.manifest.components] == [
        "skill-bundle",
        "mcp-http",
    ]
    assert first.manifest.components[1].connection_slot == "reference-docs"
    assert [file.path for file in first.files] == [
        "skills/research/SKILL.md",
        "skills/research/assets/z.bin",
    ]
    canonical = first.manifest.canonical_json()
    assert first.manifest_digest == "sha256:" + sha256(canonical.encode()).hexdigest()
    expected = json.dumps(
        {
            "manifest": json.loads(canonical),
            "files": [[file.path, file.size, file.sha256] for file in first.files],
        },
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    assert first.package_digest == "sha256:" + sha256(expected.encode()).hexdigest()
    (bundle / "plugin.json").write_text(json.dumps(_v2(), indent=4, sort_keys=True))
    assert load_plugin_package(bundle).package_digest == first.package_digest
    (assets / "z.bin").rename(assets / "a.bin")
    assert load_plugin_package(bundle).package_digest != first.package_digest


def test_v1_normalization_preserves_legacy_manifest_digest(tmp_path: Path) -> None:
    from agent_integrations.plugins.package_integrity import load_plugin_package

    bundle = _legacy_bundle(tmp_path)
    original = load_manifest(bundle)
    package = load_plugin_package(bundle)
    assert package.manifest.manifest_version == "0.2"
    assert len(package.manifest.components) == 1
    assert package.manifest.components[0].id == original.id
    assert package.manifest_digest == original.content_digest()
    assert package.package_digest != package.manifest_digest


def test_legacy_mcp_endpoint_is_not_a_connection_binding(tmp_path: Path) -> None:
    from agent_integrations.plugins.package_integrity import load_plugin_package

    bundle = _legacy_bundle(tmp_path)
    (bundle / "skills" / "research" / "SKILL.md").unlink()
    (bundle / "skills" / "research").rmdir()
    (bundle / "skills").rmdir()
    document = {
        "id": "reference-docs",
        "version": "1.0.0",
        "scope": "user",
        "entry": {
            "kind": "mcp-http",
            "url": "https://example.invalid",
            "bearer_token_env": "TOKEN",
        },
    }
    (bundle / "plugin.json").write_text(json.dumps(document))
    first = load_plugin_package(bundle)
    component = first.manifest.components[0]
    assert component.model_dump() == {
        "id": "reference-docs",
        "kind": "mcp-http",
        "connection_slot": "reference-docs",
    }
    document["entry"] = {"kind": "mcp-http", "url": "https://other.invalid"}
    (bundle / "plugin.json").write_text(json.dumps(document))
    second = load_plugin_package(bundle)
    assert second.manifest == first.manifest
    assert second.package_digest != first.package_digest


@pytest.mark.parametrize(
    "entry",
    [
        {"kind": "mcp-stdio", "command": "/usr/bin/example"},
        {"kind": "hook", "command": "/usr/bin/example"},
        {"kind": "skill-bundle", "skill_root": "skills/research", "command": "/bin/sh"},
    ],
)
def test_cloud_rejects_legacy_execution_or_mixed_shapes(
    tmp_path: Path, entry: dict[str, object]
) -> None:
    from agent_integrations.plugins.package_integrity import PluginPackageError, load_plugin_package

    bundle = _legacy_bundle(tmp_path)
    document = json.loads((bundle / "plugin.json").read_text())
    document["entry"] = entry
    assert PluginManifest.validate_document(document).entry.kind == entry["kind"]
    (bundle / "plugin.json").write_text(json.dumps(document))
    with pytest.raises(PluginPackageError):
        load_plugin_package(bundle)


@pytest.mark.parametrize(
    "components",
    [
        [],
        [{"id": "repeat", "kind": "mcp-http", "connection_slot": "docs"}] * 2,
        [{"id": "server", "kind": "mcp-stdio", "command": "/bin/sh"}],
        [{"id": "server", "kind": "mcp-http", "connection_slot": "https://example.invalid"}],
        [
            {
                "id": "server",
                "kind": "mcp-http",
                "connection_slot": "docs",
                "url": "https://example.invalid",
            }
        ],
        [
            {
                "id": "server",
                "kind": "mcp-http",
                "connection_slot": "docs",
                "skill_root": "skills/research",
            }
        ],
        [{"id": "guide", "kind": "skill-bundle", "skill_root": "/outside"}],
        [{"id": "guide", "kind": "skill-bundle", "skill_root": "skills/../outside"}],
        [{"id": "guide", "kind": "skill-bundle", "skill_root": "skills\\research"}],
        [{"id": "guide", "kind": "skill-bundle", "skill_root": "skills./research"}],
        [{"id": "guide", "kind": "skill-bundle", "skill_root": "skills/NUL"}],
        [
            {"id": f"server-{index}", "kind": "mcp-http", "connection_slot": "docs"}
            for index in range(33)
        ],
    ],
)
def test_v2_rejects_unsafe_component_shapes(components: list[dict[str, object]]) -> None:
    from agent_core.domain.plugin_packages import PluginPackageManifest

    with pytest.raises(ValueError):
        PluginPackageManifest.validate_document(_v2(components=components))


@pytest.mark.parametrize(
    "manifest",
    [
        '{"id":"first","id":"second"}',
        json.dumps(_v2()).replace(
            '"connection_slot": "reference-docs"',
            '"connection_slot":"docs","connection_slot":"other"',
        ),
    ],
)
def test_duplicate_json_keys_are_rejected(tmp_path: Path, manifest: str) -> None:
    from agent_integrations.plugins.package_integrity import PluginPackageError, load_plugin_package

    bundle = _legacy_bundle(tmp_path)
    (bundle / "plugin.json").write_text(manifest)
    with pytest.raises(PluginPackageError, match="duplicate_json_key"):
        load_plugin_package(bundle)


@pytest.mark.parametrize("target", ["skill", "file", "manifest"])
def test_cloud_rejects_symlink_escapes(tmp_path: Path, target: str) -> None:
    from agent_integrations.plugins.package_integrity import PluginPackageError, load_plugin_package

    bundle = _legacy_bundle(tmp_path)
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "SKILL.md").write_bytes(SKILL)
    if target == "skill":
        (bundle / "skills" / "linked").symlink_to(outside, target_is_directory=True)
    elif target == "file":
        (bundle / "skills" / "research" / "SKILL.md").unlink()
        (bundle / "skills" / "research" / "SKILL.md").symlink_to(outside / "SKILL.md")
    else:
        (bundle / "plugin.json").rename(outside / "plugin.json")
        (bundle / "plugin.json").symlink_to(outside / "plugin.json")
    with pytest.raises(PluginPackageError, match="unsupported_entry"):
        load_plugin_package(bundle)


@pytest.mark.parametrize("paths", [("A", "a"), ("é", "e\u0301")])
def test_normalized_file_collisions_are_rejected(
    tmp_path: Path, paths: tuple[str, str], monkeypatch: pytest.MonkeyPatch
) -> None:
    from agent_integrations.plugins.package_integrity import PluginPackageError, load_plugin_package

    bundle = _legacy_bundle(tmp_path)
    assets = bundle / "skills" / "research" / "assets"
    assets.mkdir()
    for name in paths:
        (assets / name).write_bytes(b"x")
    # macOS coalesces these names. Simulate the directory entries that Linux
    # permits; rejection must precede opening the second conflicting name.
    if len(list(assets.iterdir())) < 2:
        scan_directory = os.scandir

        @contextmanager
        def conflicting_entries(fd: int) -> Iterator[Iterator[os.DirEntry[str] | SimpleNamespace]]:
            with scan_directory(fd) as scan:
                entries = list(scan)
                if len(entries) == 1 and entries[0].name not in {"skills", "research"}:
                    yield iter(SimpleNamespace(name=name) for name in paths)
                else:
                    yield iter(entries)

        monkeypatch.setattr(os, "scandir", conflicting_entries)
    with pytest.raises(PluginPackageError, match="path_conflict"):
        load_plugin_package(bundle)


@pytest.mark.parametrize(
    "path,content",
    [
        ("unclaimed.txt", b"unclaimed"),
        ("skills/research/unexpected.txt", b"unsupported"),
        ("skills/research/SKILL.md", b"missing frontmatter"),
        ("skills/research/SKILL.md", SKILL + b"x" * 32768),
        ("skills/research/assets/file.", b"unsafe path"),
    ],
    ids=["unclaimed", "unsupported", "bad-skill", "large-skill", "unsafe-path"],
)
def test_actual_contents_use_existing_skill_validation(
    tmp_path: Path, path: str, content: bytes
) -> None:
    from agent_integrations.plugins.package_integrity import PluginPackageError, load_plugin_package

    bundle = _legacy_bundle(tmp_path)
    destination = bundle / path
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_bytes(content)
    with pytest.raises(PluginPackageError):
        load_plugin_package(bundle)


def test_missing_skill_and_arbitrary_archive_input_are_rejected(tmp_path: Path) -> None:
    from agent_integrations.plugins.package_integrity import PluginPackageError, load_plugin_package

    bundle = _legacy_bundle(tmp_path)
    (bundle / "skills" / "research" / "SKILL.md").unlink()
    with pytest.raises(PluginPackageError):
        load_plugin_package(bundle)
    archive = tmp_path / "plugin.zip"
    archive.write_bytes(b"not an accepted directory package")
    with pytest.raises(PluginPackageError):
        load_plugin_package(archive)


def test_directory_limits_reuse_skill_budgets(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from agent_integrations.plugins import package_integrity as packages

    bundle = _legacy_bundle(tmp_path)
    monkeypatch.setattr(packages, "MAX_ENTRIES", 2)
    with pytest.raises(packages.PluginPackageError, match="too_many_entries"):
        packages.load_plugin_package(bundle)
    monkeypatch.setattr(packages, "MAX_ENTRIES", 1000)
    monkeypatch.setattr(packages, "MAX_EXPANDED_BYTES", 10)
    with pytest.raises(packages.PluginPackageError, match="package_too_large"):
        packages.load_plugin_package(bundle)


def test_unsafe_empty_directory_is_rejected(tmp_path: Path) -> None:
    from agent_integrations.plugins.package_integrity import PluginPackageError, load_plugin_package

    bundle = _legacy_bundle(tmp_path)
    (bundle / "unsafe.").mkdir()
    with pytest.raises(PluginPackageError):
        load_plugin_package(bundle)


def test_directory_inventory_is_bounded_before_materializing_names(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from agent_integrations.plugins import package_integrity as packages

    bundle = _legacy_bundle(tmp_path)

    def unbounded_listing(fd: int) -> list[str]:
        pytest.fail("directory listing must stream under the entry budget")

    monkeypatch.setattr(packages.os, "listdir", unbounded_listing)
    monkeypatch.setattr(packages, "MAX_ENTRIES", 2)
    with pytest.raises(packages.PluginPackageError, match="too_many_entries"):
        packages.load_plugin_package(bundle)


def test_v2_root_readme_is_hashed_metadata_not_executable_content(tmp_path: Path) -> None:
    from agent_integrations.plugins.package_integrity import PluginPackageError, load_plugin_package

    root = tmp_path / "described"
    root.mkdir()
    (root / "plugin.json").write_text(
        json.dumps(
            _v2(
                components=[
                    {"id": "docs", "kind": "mcp-http", "connection_slot": "reference-docs"},
                ]
            )
        )
    )
    (root / "README.md").write_text("Operator documentation")
    first = load_plugin_package(root)
    (root / "README.md").write_text("Updated operator documentation")
    assert load_plugin_package(root).package_digest != first.package_digest
    (root / "undeclared.py").write_text("raise RuntimeError('MUST_NOT_RUN')")
    with pytest.raises(PluginPackageError, match="unclaimed_file"):
        load_plugin_package(root)


def test_legacy_readme_rules_remain_unchanged(tmp_path: Path) -> None:
    from agent_integrations.plugins.package_integrity import PluginPackageError, load_plugin_package

    root = _legacy_bundle(tmp_path)
    (root / "README.md").write_text("Not declared by the legacy Skill")
    with pytest.raises(PluginPackageError, match="unclaimed_file"):
        load_plugin_package(root)
